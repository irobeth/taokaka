import asyncio
from collections import Counter

from modules.module import Module
from stopwords import extract_keywords

_INTERVAL = 15  # seconds between keyword refreshes
_TOP_N = 20     # how many keywords to publish


class KeywordExtractor(Module):
    """Lightweight extractor that periodically scans recent conversation for
    high-frequency non-stopword terms and publishes them to
    signals.extractor_signals["conversation_keywords"].

    Runs on its own schedule, fully outside the prompt loop."""

    def __init__(self, signals, enabled=True):
        super().__init__(signals, enabled)
        self._last_history_len = 0

    async def run(self):
        while not self.signals.terminate:
            await asyncio.sleep(_INTERVAL)

            if not self.enabled:
                continue

            history = self.signals.history
            if len(history) <= self._last_history_len:
                continue

            # Scan the last 40 messages
            recent = history[-40:]
            all_text = " ".join(
                msg.get("content", "") for msg in recent if msg.get("content")
            )

            tokens = extract_keywords(all_text)
            counts = Counter(tokens)
            top = [kw for kw, _ in counts.most_common(_TOP_N)]

            self.signals.extractor_signals["conversation_keywords"] = top
            self._last_history_len = len(history)
