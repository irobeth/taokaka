import asyncio
import time

import requests

from constants import AI_NAME, BANNED_TOKENS, LLM_ENDPOINT
from modules.module import Module
from stopwords import extract_keywords

_MIN_MESSAGES = 10
_INTERVAL = 60

_PROMPT = (
    "Given this chat transcript, identify the topic at hand; produce a summary of the "
    "users in the transcript and their perspectives on the topic, include a short "
    "summary of the discussion (no more than 3 or 4 sentences).\n\n"
    "After the summary, on a new line starting with 'KEYWORDS:', list 5-10 single-word "
    "keywords that capture the most relevant topics, entities, and themes from this "
    "conversation. Separate keywords with commas."
)


class ZeitgeistExtractor(Module):
    """Background extractor that periodically summarizes conversation history."""

    def __init__(self, signals, zeitgeist_injector, enabled=True):
        super().__init__(signals, enabled)
        self.zeitgeist_injector = zeitgeist_injector
        self._last_summary_time = 0.0
        self._last_summarized_count = 0

    async def run(self):
        while not self.signals.terminate:
            await asyncio.sleep(10)

            if not self.enabled:
                continue

            history = self.signals.history
            now = time.time()

            if len(history) < _MIN_MESSAGES:
                continue

            time_elapsed = (now - self._last_summary_time) >= _INTERVAL
            new_activity = len(history) > self._last_summarized_count

            if not (time_elapsed and new_activity):
                continue

            await asyncio.get_event_loop().run_in_executor(
                None, self._generate_summary, list(history)
            )

    def _generate_summary(self, history):
        lines = []
        for msg in history[-40:]:
            role = msg.get("role", "")
            content = msg.get("content", "").strip()
            if not content:
                continue
            if role == "assistant":
                lines.append(f"{AI_NAME}: {content}")
            else:
                lines.append(content)

        if not lines:
            return

        transcript = "\n".join(lines)

        data = {
            "mode": "instruct",
            "max_tokens": 300,
            "skip_special_tokens": False,
            "custom_token_bans": BANNED_TOKENS,
            "stop": ["<|eot_id|>"],
            "messages": [{"role": "user", "content": f"{transcript}\n\n{_PROMPT}"}],
        }

        try:
            response = requests.post(
                LLM_ENDPOINT + "/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json=data,
                verify=False,
                timeout=30,
            )
            raw = response.json()["choices"][0]["message"]["content"].strip()

            # Split out KEYWORDS: line if the LLM produced one
            summary = raw
            llm_keywords = []
            for line in raw.splitlines():
                if line.strip().upper().startswith("KEYWORDS:"):
                    keyword_text = line.split(":", 1)[1].strip()
                    llm_keywords = [k.strip().lower() for k in keyword_text.split(",") if k.strip()]
                    summary = raw[:raw.index(line)].strip()
                    break

            # Also extract keywords from the transcript itself via stopword filtering
            transcript_keywords = extract_keywords(transcript)

            # Merge: LLM keywords first (higher signal), then transcript keywords
            seen = set()
            merged = []
            for kw in llm_keywords + transcript_keywords:
                if kw not in seen:
                    seen.add(kw)
                    merged.append(kw)

            self.zeitgeist_injector.set_summary(summary)
            self.signals.extractor_signals["keywords"] = merged
            self._last_summary_time = time.time()
            self._last_summarized_count = len(self.signals.history)
        except Exception as e:
            print(f"Zeitgeist error: {e}")
