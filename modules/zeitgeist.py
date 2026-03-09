import asyncio
import time

import requests

from constants import AI_NAME, BANNED_TOKENS, LLM_ENDPOINT
from prompts import strip_think
from modules.module import Module

_MIN_MESSAGES = 10        # don't attempt until at least this many history entries
_INTERVAL = 60            # seconds between resummarisation checks

_PROMPT = (
    "Given this chat transcript, identify the topic at hand; produce a summary of the "
    "users in the transcript and their perspectives on the topic, include a short "
    "summary of the discussion (no more than 3 or 4 sentences)."
)


class Zeitgeist(Module):

    def __init__(self, signals, enabled=True):
        super().__init__(signals, enabled)
        # Inject just before Discord messages (priority 160) so it provides
        # context that frames the incoming chat.
        self.prompt_injection.priority = 155

        self._summary = ""
        self._last_summary_time = 0.0
        self._last_summarized_count = 0

    def get_prompt_injection(self):
        if self._summary:
            self.prompt_injection.text = (
                f"<ZEITGEIST>\n{self._summary}\n</ZEITGEIST>\n"
            )
        else:
            self.prompt_injection.text = ""
        return self.prompt_injection

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
            summary = strip_think(response.json()["choices"][0]["message"]["content"]).strip()
            self._summary = summary
            self.signals.zeitgeist = summary
            self._last_summary_time = time.time()
            self._last_summarized_count = len(self.signals.history)
        except Exception as e:
            print(f"Zeitgeist error: {e}")
