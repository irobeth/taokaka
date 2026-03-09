import asyncio
import copy
import uuid
from datetime import datetime

import requests

from constants import AI_NAME, BANNED_TOKENS, HOST_NAME, LLM_ENDPOINT, MEMORY_PROMPT, MEMORY_TYPES, STOP_STRINGS
from modules.module import Module


class MemoryExtractor(Module):
    """Background extractor that periodically reflects on conversation history
    and generates new memories via LLM, storing them in the shared ChromaDB collection."""

    def __init__(self, signals, memory_injector, enabled=True):
        super().__init__(signals, enabled)
        self.memory_injector = memory_injector
        self.processed_count = 0

    def _parse_memory_block(self, block):
        """Parse a {qa}-delimited block into (document, metadata_dict)."""
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
                        raw_title = part[6:].strip()
                        metadata["title"] = " ".join(raw_title.split()[:3])
            else:
                document_lines.append(line)

        document = "\n".join(document_lines).strip()
        return document, metadata

    async def run(self):
        collection = self.memory_injector.collection

        while not self.signals.terminate:
            if self.processed_count > len(self.signals.history):
                self.processed_count = 0

            if len(self.signals.history) - self.processed_count >= 20:
                print("MEMORY: Generating new memories")

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
                    "skip_special_tokens": False,
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

                new_pairs = []
                for block in raw_memories.split("{qa}"):
                    block = block.strip()
                    if block == "":
                        continue
                    document, metadata = self._parse_memory_block(block)
                    if document:
                        collection.upsert(
                            [str(uuid.uuid4())],
                            documents=[document],
                            metadatas=[metadata],
                        )
                        new_pairs.append(document)

                if new_pairs:
                    self.signals.recent_memories = (self.signals.recent_memories + new_pairs)[-20:]
                    self.memory_injector._refresh_all_memories()

                self.processed_count = len(self.signals.history)

            await asyncio.sleep(5)
