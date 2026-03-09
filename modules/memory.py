from modules.module import Module
from constants import *
from chromadb.config import Settings
from datetime import datetime
import chromadb
import requests
import json
import uuid
import asyncio
import copy


class Memory(Module):

    def __init__(self, signals, enabled=True):
        super().__init__(signals, enabled)

        self.API = self.API(self)
        self.prompt_injection.text = ""
        self.prompt_injection.priority = 60

        self.processed_count = 0

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

    def _parse_memory_block(self, block):
        """Parse a {qa}-delimited block into (document, metadata_dict).

        Expected format:
            type:about_user|user:irobeth|keywords:programming,python
            Q: What does irobeth enjoy? A: irobeth enjoys programming.

        Falls back to default metadata if no metadata line is detected.
        """
        lines = block.strip().split("\n")
        metadata = {
            "type": "short_term",
            "related_user": "personal",
            "keywords": "",
            "title": "",
            "created_at": datetime.now().isoformat(),
        }
        document_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Check if this line matches the metadata format: type:...|user:...|keywords:...
            if line.startswith("type:") and "|" in line:
                parts = line.split("|")
                for part in parts:
                    if part.startswith("type:"):
                        val = part[5:].strip()
                        if val in MEMORY_TYPES:
                            metadata["type"] = val
                    elif part.startswith("user:"):
                        metadata["related_user"] = part[5:].strip()
                    elif part.startswith("keywords:"):
                        metadata["keywords"] = part[9:].strip()
                    elif part.startswith("title:"):
                        # Clamp to 3 words max
                        raw_title = part[6:].strip()
                        metadata["title"] = " ".join(raw_title.split()[:3])
            else:
                document_lines.append(line)

        document = "\n".join(document_lines).strip()
        return document, metadata

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

    async def run(self):
        # Periodically, check if at least 20 new messages have been sent, and if so, generate 3 question-answer pairs
        # to be stored into memory.
        # This is a technique called reflection. You essentially ask the AI what information is important in the recent
        # conversation, and it is converted into a memory so that it can be recalled later.
        while not self.signals.terminate:
            if self.processed_count > len(self.signals.history):
                self.processed_count = 0

            if len(self.signals.history) - self.processed_count >= 20:
                print("MEMORY: Generating new memories")

                # Copy the latest unprocessed messages
                messages = copy.deepcopy(self.signals.history[-(len(self.signals.history) - self.processed_count):])

                for message in messages:
                    if message["role"] == "user" and message["content"] != "":
                        message["content"] = HOST_NAME + ": " + message["content"] + "\n"
                    elif message["role"] == "assistant" and message["content"] != "":
                        message["content"] = AI_NAME + ": " + message["content"] + "\n"

                chat_section = ""
                for message in messages:
                    chat_section += message["content"]

                data = {
                    "mode": "instruct",
                    "max_tokens": 400,
                    "skip_special_tokens": False,  # Necessary for Llama 3
                    "custom_token_bans": BANNED_TOKENS,
                    "stop": STOP_STRINGS.remove("\n"),
                    "messages": [{
                        "role": "user",
                        "content": chat_section + MEMORY_PROMPT
                    }]
                }
                headers = {"Content-Type": "application/json"}

                response = requests.post(LLM_ENDPOINT + "/v1/chat/completions", headers=headers, json=data, verify=False)
                from prompts import strip_think
                raw_memories = strip_think(response.json()['choices'][0]['message']['content'])

                # Split each Q&A section and add the new memory to the database
                new_pairs = []
                for block in raw_memories.split("{qa}"):
                    block = block.strip()
                    if block == "":
                        continue
                    document, metadata = self._parse_memory_block(block)
                    if document:
                        self.collection.upsert(
                            [str(uuid.uuid4())],
                            documents=[document],
                            metadatas=[metadata],
                        )
                        new_pairs.append(document)

                if new_pairs:
                    self.signals.recent_memories = (self.signals.recent_memories + new_pairs)[-20:]
                    self._refresh_all_memories()

                self.processed_count = len(self.signals.history)

            await asyncio.sleep(5)

    class API:
        def __init__(self, outer):
            self.outer = outer

        def create_memory(self, data, metadata=None):
            id = str(uuid.uuid4())
            if metadata is None:
                metadata = {}
            # Fill defaults for any missing fields
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
            # Query with the old "short-term" type AND the new "short_term" type
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

                # Sort memories by distance
                data = sorted(data, key=lambda x: x["distance"])
            return data
