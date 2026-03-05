import asyncio
import time

import requests

from constants import AI_NAME, BANNED_TOKENS, LLM_ENDPOINT
from modules.module import Module

_MIN_MESSAGES = 10
_INTERVAL = 60

_PROMPT = (
    "Given this chat transcript, identify the topic at hand; produce a summary of the "
    "users in the transcript and their perspectives on the topic, include a short "
    "summary of the discussion (no more than 3 or 4 sentences)."
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
            summary = response.json()["choices"][0]["message"]["content"].strip()
            self.zeitgeist_injector.set_summary(summary)
            self._last_summary_time = time.time()
            self._last_summarized_count = len(self.signals.history)
        except Exception as e:
            print(f"Zeitgeist error: {e}")
