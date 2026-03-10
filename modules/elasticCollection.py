"""Drop-in replacement for ChromaDB collection backed by Elasticsearch.

Exposes the same interface used throughout the codebase:
  - get(where=None)
  - query(query_texts, n_results)
  - upsert(ids, documents, metadatas)
  - delete(id)
  - count()
"""

import warnings
warnings.filterwarnings("ignore", message=".*_body.*")

from elasticsearch import Elasticsearch, helpers
from sentence_transformers import SentenceTransformer

_INDEX_MAPPING = {
    "properties": {
        "document": {"type": "text", "analyzer": "standard"},
        "embedding": {
            "type": "dense_vector",
            "dims": 384,
            "index": True,
            "similarity": "cosine",
        },
        "type": {"type": "keyword"},
        "related_user": {"type": "keyword"},
        "keywords": {
            "type": "text",
            "fields": {"raw": {"type": "keyword"}},
        },
        "title": {
            "type": "text",
            "fields": {"raw": {"type": "keyword"}},
        },
        "source": {"type": "keyword"},
        "created_at": {
            "type": "date",
            "format": "strict_date_optional_time||epoch_millis",
            "ignore_malformed": True,
        },
        "mood_emotion": {"type": "keyword"},
        "mood_intensity": {"type": "keyword"},
        "mood_inertia": {"type": "keyword"},
    }
}


class ElasticCollection:
    """ChromaDB-compatible collection backed by Elasticsearch with hybrid search."""

    def __init__(self, es_url="http://localhost:9200", index_name="neuro_memories"):
        self.es = Elasticsearch(es_url)
        self.index_name = index_name
        self._model = SentenceTransformer("all-MiniLM-L6-v2")

        if not self.es.indices.exists(index=self.index_name):
            self.es.indices.create(index=self.index_name, mappings=_INDEX_MAPPING)

    # ── ChromaDB-compatible interface ──

    def count(self):
        """Return total number of documents in the index."""
        self.es.indices.refresh(index=self.index_name)
        return self.es.count(index=self.index_name)["count"]

    def get(self, where=None, ids=None):
        """Retrieve documents, optionally filtered.

        Returns {"ids": [], "documents": [], "metadatas": []}
        """
        if ids is not None:
            return self._get_by_ids(ids if isinstance(ids, list) else [ids])

        if where:
            q = self._translate_where(where)
        else:
            q = {"match_all": {}}

        resp = self.es.search(index=self.index_name, query=q, size=10000)
        return self._hits_to_get_result(resp["hits"]["hits"])

    def query(self, query_texts, n_results=10):
        """Hybrid search: BM25 full-text + kNN vector similarity.

        Returns {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        """
        query_text = query_texts if isinstance(query_texts, str) else query_texts[0]
        query_vector = self._model.encode(query_text).tolist()

        resp = self.es.search(
            index=self.index_name,
            size=n_results,
            query={"match": {"document": {"query": query_text, "boost": 0.3}}},
            knn={
                "field": "embedding",
                "query_vector": query_vector,
                "k": n_results,
                "num_candidates": max(n_results * 10, 100),
            },
        )
        hits = resp["hits"]["hits"]

        ids, docs, metas, distances = [], [], [], []
        for hit in hits:
            src = hit["_source"]
            ids.append(hit["_id"])
            docs.append(src.get("document", ""))
            metas.append(self._extract_metadata(src))
            # Convert ES score to distance (lower = more similar, like ChromaDB)
            distances.append(1.0 / (1.0 + hit["_score"]))

        return {
            "ids": [ids],
            "documents": [docs],
            "metadatas": [metas],
            "distances": [distances],
        }

    def upsert(self, ids, documents=None, metadatas=None):
        """Insert or update documents with embeddings."""
        if documents is None:
            documents = []
        if metadatas is None:
            metadatas = [{}] * len(ids)

        # Handle single-id case (ChromaDB accepts both string and list)
        if isinstance(ids, str):
            ids = [ids]
        if isinstance(documents, str):
            documents = [documents]
        if isinstance(metadatas, dict):
            metadatas = [metadatas]

        embeddings = self._model.encode(documents).tolist()

        actions = []
        for i, doc_id in enumerate(ids):
            body = {
                "document": documents[i] if i < len(documents) else "",
                "embedding": embeddings[i],
            }
            if i < len(metadatas):
                body.update(metadatas[i])

            actions.append({
                "_index": self.index_name,
                "_id": doc_id,
                "_source": body,
            })

        helpers.bulk(self.es, actions, refresh=True)

    def delete(self, ids):
        """Delete by ID (string or list)."""
        if isinstance(ids, str):
            ids = [ids]
        for doc_id in ids:
            try:
                self.es.delete(index=self.index_name, id=doc_id, refresh=True)
            except Exception:
                pass  # Already deleted or not found

    # ── Admin methods (used by MemoryInjector.API) ──

    def wipe(self):
        """Delete and recreate the index."""
        if self.es.indices.exists(index=self.index_name):
            self.es.indices.delete(index=self.index_name)
        self.es.indices.create(index=self.index_name, mappings=_INDEX_MAPPING)

    # ── Internal helpers ──

    def _get_by_ids(self, ids):
        """Fetch specific documents by their IDs."""
        result_ids, docs, metas = [], [], []
        for doc_id in ids:
            try:
                resp = self.es.get(index=self.index_name, id=doc_id)
                src = resp["_source"]
                result_ids.append(resp["_id"])
                docs.append(src.get("document", ""))
                metas.append(self._extract_metadata(src))
            except Exception:
                pass
        return {"ids": result_ids, "documents": docs, "metadatas": metas}

    def _translate_where(self, where):
        """Convert ChromaDB where-clause to ES query DSL."""
        if "$and" in where:
            clauses = [self._translate_where(c) for c in where["$and"]]
            return {"bool": {"must": clauses}}
        if "$or" in where:
            clauses = [self._translate_where(c) for c in where["$or"]]
            return {"bool": {"should": clauses, "minimum_should_match": 1}}

        # Simple equality: {"type": "mood"}
        must = []
        for key, value in where.items():
            must.append({"term": {key: value}})

        if len(must) == 1:
            return must[0]
        return {"bool": {"must": must}}

    def _extract_metadata(self, source):
        """Extract metadata fields from an ES document source, excluding internal fields."""
        skip = {"document", "embedding"}
        return {k: v for k, v in source.items() if k not in skip}

    def _hits_to_get_result(self, hits):
        """Convert ES hits to ChromaDB-style get result."""
        ids, docs, metas = [], [], []
        for hit in hits:
            src = hit["_source"]
            ids.append(hit["_id"])
            docs.append(src.get("document", ""))
            metas.append(self._extract_metadata(src))
        return {"ids": ids, "documents": docs, "metadatas": metas}
