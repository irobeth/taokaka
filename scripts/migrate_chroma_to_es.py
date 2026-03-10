#!/usr/bin/env python3
"""Migrate all memories from ChromaDB to Elasticsearch.

Usage:
    python scripts/migrate_chroma_to_es.py [--chroma-path ./memories/chroma.db] [--es-url http://localhost:9200]

Preserves original document IDs so references remain valid.
"""

import argparse
import sys
import os

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Migrate ChromaDB memories to Elasticsearch")
    parser.add_argument("--chroma-path", default="./memories/chroma.db", help="Path to ChromaDB database")
    parser.add_argument("--es-url", default="http://localhost:9200", help="Elasticsearch URL")
    parser.add_argument("--index", default="neuro_memories", help="ES index name")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be migrated without writing")
    args = parser.parse_args()

    # Import ChromaDB to read existing data
    import chromadb
    from chromadb.config import Settings

    print(f"Opening ChromaDB at {args.chroma_path}...")
    client = chromadb.PersistentClient(path=args.chroma_path, settings=Settings(anonymized_telemetry=False))
    collection = client.get_or_create_collection(name="neuro_collection")
    total = collection.count()
    print(f"Found {total} memories in ChromaDB")

    if total == 0:
        print("Nothing to migrate.")
        return

    # Fetch all
    all_data = collection.get()
    ids = all_data["ids"]
    documents = all_data["documents"]
    metadatas = all_data["metadatas"]

    print(f"Fetched {len(ids)} documents")

    # Count by type
    type_counts = {}
    for meta in metadatas:
        t = meta.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    print("Memory types:")
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")

    if args.dry_run:
        print("\n[DRY RUN] Would migrate the above. Pass without --dry-run to execute.")
        return

    # Import ES wrapper
    from modules.elasticCollection import ElasticCollection

    print(f"\nConnecting to Elasticsearch at {args.es_url}...")
    es_collection = ElasticCollection(es_url=args.es_url, index_name=args.index)

    existing = es_collection.count()
    if existing > 0:
        response = input(f"ES index '{args.index}' already has {existing} documents. Wipe and reimport? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return
        es_collection.wipe()
        # Recreate index
        es_collection = ElasticCollection(es_url=args.es_url, index_name=args.index)

    # Migrate in batches
    batch_size = 50
    migrated = 0
    errors = 0

    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i:i + batch_size]
        batch_docs = documents[i:i + batch_size]
        batch_metas = metadatas[i:i + batch_size]

        try:
            es_collection.upsert(batch_ids, documents=batch_docs, metadatas=batch_metas)
            migrated += len(batch_ids)
            print(f"  Migrated {migrated}/{len(ids)}...")
        except Exception as e:
            errors += len(batch_ids)
            print(f"  ERROR migrating batch {i}-{i + len(batch_ids)}: {e}")

    print(f"\nMigration complete: {migrated} migrated, {errors} errors")
    print(f"ES index '{args.index}' now has {es_collection.count()} documents")


if __name__ == "__main__":
    main()
