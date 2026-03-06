import asyncio
import copy
import time
import uuid
from datetime import datetime

import requests

from constants import (
    AI_NAME, BANNED_TOKENS, CURIOSITY_EVAL_PROMPT, CURIOSITY_PROMPT,
    HOST_NAME, LLM_ENDPOINT, MEMORY_TYPES,
)
from modules.module import Module


class CuriosityExtractor(Module):
    """Generates short-term 'curiosity' memories after each LLM prompt cycle.
    On patience expiry, evaluates existing curiosities: answered ones get
    promoted to long_term, stale ones get dropped."""

    def __init__(self, signals, memory_injector, interface=None, enabled=True):
        super().__init__(signals, enabled)
        self.memory_injector = memory_injector
        self.interface = interface
        self._last_prompt_time = 0.0    # tracks extractor_signals["prompt_completed"]
        self._last_eval_time = 0.0

    def _log(self, msg):
        if self.interface:
            self.interface.trace(msg, source="Curiosity", level="info")
        else:
            print(f"CURIOSITY: {msg}")

    def _build_chat_section(self, messages):
        out = ""
        for msg in messages:
            if msg["role"] == "user" and msg["content"]:
                out += HOST_NAME + ": " + msg["content"] + "\n"
            elif msg["role"] == "assistant" and msg["content"]:
                out += AI_NAME + ": " + msg["content"] + "\n"
        return out

    def _llm_call(self, prompt, max_tokens=400):
        data = {
            "mode": "instruct",
            "max_tokens": max_tokens,
            "skip_special_tokens": False,
            "custom_token_bans": BANNED_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = requests.post(
            LLM_ENDPOINT + "/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=data, verify=False, timeout=30,
        )
        return resp.json()["choices"][0]["message"]["content"]

    def _parse_block(self, block):
        lines = block.strip().split("\n")
        metadata = {
            "type": "short_term",
            "related_user": "personal",
            "keywords": "",
            "title": "",
            "source": "curiosity",
            "created_at": datetime.now().isoformat(),
        }
        doc_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("type:") and "|" in line:
                for part in line.split("|"):
                    if part.startswith("type:"):
                        val = part[5:].strip()
                        if val in MEMORY_TYPES:
                            metadata["type"] = val
                    elif part.startswith("user:"):
                        metadata["related_user"] = part[5:].strip()
                    elif part.startswith("keywords:"):
                        metadata["keywords"] = part[9:].strip()
                    elif part.startswith("title:"):
                        metadata["title"] = " ".join(part[6:].strip().split()[:3])
            else:
                doc_lines.append(line)
        return "\n".join(doc_lines).strip(), metadata

    def _get_curiosity_memories(self):
        collection = self.memory_injector.collection
        try:
            results = collection.get(
                where={"$and": [{"type": "short_term"}, {"source": "curiosity"}]}
            )
        except Exception:
            results = collection.get(where={"type": "short_term"})
            ids, docs, metas = [], [], []
            for i, meta in enumerate(results["metadatas"]):
                if meta.get("source") == "curiosity":
                    ids.append(results["ids"][i])
                    docs.append(results["documents"][i])
                    metas.append(results["metadatas"][i])
            results = {"ids": ids, "documents": docs, "metadatas": metas}
        return results

    def _generate_curiosities(self):
        """Generate curiosities from recent conversation."""
        history = self.signals.history
        if len(history) < 3:
            return

        messages = copy.deepcopy(history[-20:])
        chat_section = self._build_chat_section(messages)
        if not chat_section.strip():
            return

        self._log("Generating curiosities...")
        raw = self._llm_call(chat_section + CURIOSITY_PROMPT)
        collection = self.memory_injector.collection
        new = []
        for block in raw.split("{qa}"):
            block = block.strip()
            if not block:
                continue
            doc, meta = self._parse_block(block)
            meta["type"] = "short_term"
            meta["source"] = "curiosity"
            if doc:
                collection.upsert(
                    [str(uuid.uuid4())],
                    documents=[doc],
                    metadatas=[meta],
                )
                new.append(doc)
                self._log(f"  + {doc[:80]}")

        if new:
            self.signals.recent_memories = (self.signals.recent_memories + new)[-20:]
            self.memory_injector._refresh_all_memories()
            # Publish active curiosities as extractor signal for injection
            self._publish_curiosities()

    def _evaluate_curiosities(self):
        """Review existing curiosities against recent conversation."""
        existing = self._get_curiosity_memories()
        if not existing["ids"]:
            return

        history = self.signals.history
        if len(history) < 3:
            return

        messages = copy.deepcopy(history[-30:])
        chat_section = self._build_chat_section(messages)

        self._log(f"Evaluating {len(existing['ids'])} curiosities...")

        curiosities_text = ""
        for i, doc in enumerate(existing["documents"]):
            curiosities_text += f"{i+1}. {doc}\n"

        prompt = CURIOSITY_EVAL_PROMPT.format(
            curiosities=curiosities_text,
            conversation=chat_section,
        )
        raw = self._llm_call(prompt, max_tokens=600)

        collection = self.memory_injector.collection
        responses = [r.strip() for r in raw.split("{qa}") if r.strip()]

        for i, response in enumerate(responses):
            if i >= len(existing["ids"]):
                break
            mem_id = existing["ids"][i]
            old_meta = existing["metadatas"][i]

            if response.upper().startswith("ANSWERED:"):
                answer_text = response[9:].strip()
                doc = answer_text
                meta = {
                    "type": "long_term",
                    "related_user": old_meta.get("related_user", "personal"),
                    "keywords": old_meta.get("keywords", ""),
                    "title": old_meta.get("title", ""),
                    "source": "curiosity_resolved",
                    "created_at": datetime.now().isoformat(),
                }
                if "type:" in answer_text and "|" in answer_text:
                    lines = answer_text.split("\n")
                    doc_lines = []
                    for line in lines:
                        line = line.strip()
                        if line.startswith("type:") and "|" in line:
                            for part in line.split("|"):
                                if part.startswith("type:"):
                                    val = part[5:].strip()
                                    if val in MEMORY_TYPES:
                                        meta["type"] = val
                                elif part.startswith("user:"):
                                    meta["related_user"] = part[5:].strip()
                                elif part.startswith("keywords:"):
                                    meta["keywords"] = part[9:].strip()
                                elif part.startswith("title:"):
                                    meta["title"] = " ".join(part[6:].strip().split()[:3])
                        else:
                            doc_lines.append(line)
                    doc = "\n".join(doc_lines).strip()

                if doc:
                    collection.delete(mem_id)
                    collection.upsert(
                        [str(uuid.uuid4())],
                        documents=[doc],
                        metadatas=[meta],
                    )
                    self._log(f"  PROMOTED: {doc[:80]}")

            elif response.upper().startswith("DROP"):
                collection.delete(mem_id)
                self._log(f"  DROPPED: {existing['documents'][i][:60]}")
            else:
                self._log(f"  KEPT: {existing['documents'][i][:60]}")

        self.memory_injector._refresh_all_memories()
        self._publish_curiosities()

    def _publish_curiosities(self):
        """Publish current curiosity list to extractor_signals for prompt injection."""
        existing = self._get_curiosity_memories()
        self.signals.extractor_signals["curiosities"] = existing.get("documents", [])

    async def run(self):
        while not self.signals.terminate:
            await asyncio.sleep(2)
            if not self.enabled:
                continue

            now = time.time()

            # Generate curiosities after each prompt cycle
            prompt_time = self.signals.extractor_signals.get("prompt_completed", 0)
            if prompt_time > self._last_prompt_time:
                self._last_prompt_time = prompt_time
                try:
                    self._generate_curiosities()
                except Exception as e:
                    self._log(f"Generation error: {e}")

            # Evaluate curiosities on patience expiry
            patience = self.signals.patience
            since_last_msg = now - self.signals.last_message_time if self.signals.last_message_time else 0
            since_last_eval = now - self._last_eval_time

            if (since_last_msg >= patience
                    and since_last_eval >= patience
                    and self.signals.last_message_time > 0):
                try:
                    self._evaluate_curiosities()
                except Exception as e:
                    self._log(f"Evaluation error: {e}")
                self._last_eval_time = now
