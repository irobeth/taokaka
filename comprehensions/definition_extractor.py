import asyncio
import uuid
from datetime import datetime, timedelta

import requests

from constants import BANNED_TOKENS, LLM_ENDPOINT
from prompts import load_prompt, strip_think
from modules.module import Module

_INTERVAL = 30          # seconds between checks
_DEFINITION_TTL_DAYS = 7  # definitions older than this get expired and re-evaluated

_DEFINE_PROMPT = load_prompt("definition")


class DefinitionExtractor(Module):
    """Reads keywords from the zeitgeist extractor signals, checks if we already
    have a definition memory for each one, and asks the LLM to define unknown ones.

    Definitions are stored as 'definition' type memories with a created_at timestamp.
    After _DEFINITION_TTL_DAYS, definitions expire and can be refreshed.

    When keyword_attributions are available, also creates about_user memories
    linking users to the topics they introduced."""

    def __init__(self, signals, memory_injector, interface=None, enabled=True):
        super().__init__(signals, enabled)
        self.memory_injector = memory_injector
        self.interface = interface
        self._known_words = set()       # cache of words we've already defined this session
        self._attributed_pairs = set()  # (user, keyword) pairs we've already linked

    def _log(self, msg):
        if self.interface:
            self.interface.trace(msg, source="Definitions", level="info")
        else:
            print(f"DEFINITIONS: {msg}")

    def _get_existing_definition(self, word):
        """Check ChromaDB for an existing definition of this word. Returns (id, meta) or None."""
        collection = self.memory_injector.collection
        try:
            results = collection.get(where={"type": "definition"})
        except Exception:
            return None

        for i, meta in enumerate(results["metadatas"]):
            if meta.get("title", "").lower() == word.lower():
                return results["ids"][i], results["documents"][i], meta
        return None

    def _is_expired(self, meta):
        """Check if a definition has exceeded its TTL."""
        created = meta.get("created_at", "")
        if not created:
            return True
        try:
            created_dt = datetime.fromisoformat(created)
            return datetime.now() - created_dt > timedelta(days=_DEFINITION_TTL_DAYS)
        except Exception:
            return True

    def _define_word(self, word):
        """Ask the LLM to define a word. Returns the definition string or None."""
        prompt = _DEFINE_PROMPT.format(word=word)
        data = {
            "mode": "instruct",
            "max_tokens": 1000,
            "skip_special_tokens": False,
            "custom_token_bans": BANNED_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            resp = requests.post(
                LLM_ENDPOINT + "/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json=data, verify=False, timeout=15,
            )
            definition = strip_think(resp.json()["choices"][0]["message"]["content"]).strip()
            # Clean up — some models repeat the word or add quotes
            definition = definition.lstrip(":").strip().strip('"').strip()
            return definition if definition else None
        except Exception as e:
            self._log(f"LLM error defining '{word}': {e}")
            return None

    def _store_definition(self, word, definition, old_id=None):
        """Store or update a definition in ChromaDB."""
        collection = self.memory_injector.collection
        if old_id:
            collection.delete(old_id)

        meta = {
            "type": "definition",
            "related_user": "personal",
            "keywords": word,
            "title": word,
            "source": "definition_extractor",
            "created_at": datetime.now().isoformat(),
        }
        collection.upsert(
            [str(uuid.uuid4())],
            documents=[f"{word}: {definition}"],
            metadatas=[meta],
        )
        self._log(f"Defined '{word}': {definition[:60]}")

    def _store_user_keyword_link(self, user, keyword):
        """Create an about_user memory linking a user to a topic they discussed."""
        collection = self.memory_injector.collection
        doc = f"{user} was talking about {keyword}"
        meta = {
            "type": "about_user",
            "related_user": user,
            "keywords": keyword,
            "title": f"{user} {keyword}",
            "source": "keyword_attribution",
            "created_at": datetime.now().isoformat(),
        }
        collection.upsert(
            [str(uuid.uuid4())],
            documents=[doc],
            metadatas=[meta],
        )
        self._log(f"Linked {user} -> {keyword}")

    async def run(self):
        while not self.signals.terminate:
            await asyncio.sleep(_INTERVAL)
            if not self.enabled:
                continue

            keywords = self.signals.extractor_signals.get("keywords", [])
            attributions = self.signals.extractor_signals.get("keyword_attributions", {})

            if not keywords:
                continue

            # Process definitions for keywords we haven't seen this session
            for word in keywords[:10]:  # limit per cycle
                if word in self._known_words:
                    continue

                existing = self._get_existing_definition(word)
                if existing:
                    _id, _doc, meta = existing
                    if self._is_expired(meta):
                        # Re-define expired word
                        definition = self._define_word(word)
                        if definition:
                            self._store_definition(word, definition, old_id=_id)
                    self._known_words.add(word)
                    continue

                # Unknown word — define it
                definition = self._define_word(word)
                if definition:
                    self._store_definition(word, definition)
                self._known_words.add(word)

            # Process user-keyword attributions
            for kw, users in attributions.items():
                for user in users:
                    pair = (user, kw)
                    if pair in self._attributed_pairs:
                        continue
                    self._store_user_keyword_link(user, kw)
                    self._attributed_pairs.add(pair)

            self.memory_injector._refresh_all_memories()
