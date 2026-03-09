from modules.module import Module
from constants import *
from chromadb.config import Settings
from datetime import datetime
import chromadb
import json
import uuid


class MemoryInjector(Module):

    def __init__(self, signals, enabled=True):
        super().__init__(signals, enabled)

        self.API = self.API(self)
        self.prompt_injection.text = ""
        self.prompt_injection.priority = 60

        self.chroma_client = chromadb.PersistentClient(path="./memories/chroma.db", settings=Settings(anonymized_telemetry=False))
        self.collection = self.chroma_client.get_or_create_collection(name="neuro_collection")
        print(f"MEMORY: Loaded {self.collection.count()} memories from database.")
        if self.collection.count() == 0:
            print("MEMORY: No memories found in database. Importing from memoryinit.json")
            self.API.import_json(path="./memories/memoryinit.json")

        self._refresh_all_memories()

    def _refresh_all_memories(self):
        """Load all memories from ChromaDB into signals.all_memories for the tree browser."""
        all_data = self.collection.get()
        memories = []
        for i in range(len(all_data["ids"])):
            memories.append({
                "id": all_data["ids"][i],
                "document": all_data["documents"][i],
                "metadata": all_data["metadatas"][i],
            })
        self.signals.all_memories = memories

    def get_prompt_injection(self):
        # Collect timestamped messages from all three chat sources
        combined = []

        for message in self.signals.history[-MEMORY_QUERY_MESSAGE_COUNT:]:
            ts = message.get("timestamp", 0)
            if message["role"] == "user" and message["content"] != "":
                combined.append((ts, HOST_NAME + ": " + message["content"]))
            elif message["role"] == "assistant" and message["content"] != "":
                combined.append((ts, AI_NAME + ": " + message["content"]))

        for message in self.signals.recentTwitchMessages:
            ts = message.get("timestamp", 0) if isinstance(message, dict) else 0
            text = message["text"] if isinstance(message, dict) else message
            combined.append((ts, text))

        for message in self.signals.recentDiscordMessages:
            ts = message.get("timestamp", 0) if isinstance(message, dict) else 0
            text = message["text"] if isinstance(message, dict) else message
            combined.append((ts, text))

        # Sort by timestamp
        combined.sort(key=lambda x: x[0])

        query = "[Conversation]\nHere is a recent excerpt of the conversation:\n"
        for _, text in combined:
            query += text + "\n"
        query += "[/Conversation]\n"

        # Enrich query with keywords from extractors (zeitgeist + conversation)
        keywords = self.signals.extractor_signals.get("keywords", [])
        conv_keywords = self.signals.extractor_signals.get("conversation_keywords", [])
        all_keywords = list(dict.fromkeys(keywords + conv_keywords))  # dedupe, preserve order
        if all_keywords:
            query += "[Keywords] " + ", ".join(all_keywords[:15]) + " [/Keywords]\n"

        memories = self.collection.query(query_texts=query, n_results=MEMORY_RECALL_COUNT)

        recalled = [memories['documents'][0][i] for i in range(len(memories["ids"][0]))]

        # Forced memories: always include, deduplicate against recalled
        forced_ids = self.signals.forced_memory_ids
        forced_docs = []
        if forced_ids:
            recalled_set = set(recalled)
            id_to_doc = {m["id"]: m["document"] for m in self.signals.all_memories}
            for fid in forced_ids:
                doc = id_to_doc.get(fid)
                if doc and doc not in recalled_set:
                    forced_docs.append(doc)

        self.signals.last_recalled = recalled

        # Generate injection for LLM prompt
        self.prompt_injection.text = f"<MEMORIES>\n{AI_NAME} knows these things:\n"
        for doc in recalled:
            self.prompt_injection.text += doc + "\n"
        if forced_docs:
            self.prompt_injection.text += f"{AI_NAME} is specifically focused on:\n"
            for doc in forced_docs:
                self.prompt_injection.text += doc + "\n"
        self.prompt_injection.text += "</MEMORIES>\n"

        return self.prompt_injection

    class API:
        def __init__(self, outer):
            self.outer = outer

        def create_memory(self, data, metadata=None):
            id = str(uuid.uuid4())
            if metadata is None:
                metadata = {}
            metadata.setdefault("type", "short_term")
            metadata.setdefault("related_user", "personal")
            metadata.setdefault("keywords", "")
            metadata.setdefault("title", "")
            metadata.setdefault("created_at", datetime.now().isoformat())
            self.outer.collection.upsert([id], documents=[data], metadatas=[metadata])
            self.outer._refresh_all_memories()

        def delete_memory(self, id):
            self.outer.collection.delete(id)
            self.outer._refresh_all_memories()

        def wipe(self):
            self.outer.chroma_client.reset()
            self.outer.chroma_client.create_collection(name="neuro_collection")
            self.outer._refresh_all_memories()

        def clear_short_term(self):
            for type_val in ["short-term", "short_term"]:
                try:
                    short_term_memories = self.outer.collection.get(where={"type": type_val})
                    for id in short_term_memories["ids"]:
                        self.outer.collection.delete(id)
                except Exception:
                    pass
            self.outer._refresh_all_memories()

        def import_json(self, path="./memories/memories.json"):
            with open(path, "r") as file:
                try:
                    data = json.load(file)
                except json.JSONDecodeError:
                    print("Error decoding JSON file")
                    return

            for memory in data["memories"]:
                self.outer.collection.upsert(memory["id"], documents=memory["document"], metadatas=memory["metadata"])

        def export_json(self, path="./memories/memories.json"):
            memories = self.outer.collection.get()

            data = {"memories": []}
            for i in range(len(memories["ids"])):
                data["memories"].append({"id": memories["ids"][i],
                                         "document": memories["documents"][i],
                                        "metadata": memories["metadatas"][i]})

            with open(path, "w") as file:
                json.dump(data, file)

        def get_memories(self, query=""):
            data = [];

            if query == "":
                memories = self.outer.collection.get()
                for i in range(len(memories["ids"])):
                    data.append({"id": memories["ids"][i],
                                 "document": memories["documents"][i],
                                 "metadata": memories["metadatas"][i]})
            else:
                memories = self.outer.collection.query(query_texts=query, n_results=30)
                for i in range(len(memories["ids"][0])):
                    data.append({"id": memories["ids"][0][i],
                                 "document": memories["documents"][0][i],
                                 "metadata": memories["metadatas"][0][i],
                                 "distance": memories["distances"][0][i]})

                data = sorted(data, key=lambda x: x["distance"])
            return data
