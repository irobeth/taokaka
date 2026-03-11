import copy
from constants import *
from modules.injection import Injection
from llmWrappers.abstractLLMWrapper import AbstractLLMWrapper


class _SimpleTokenizer:
    """Estimates token count at ~4 chars/token — good enough for context management."""
    def apply_chat_template(self, messages, tokenize=True, return_tensors=None):
        text = "".join(m.get("content", "") for m in messages)
        return [[0] * max(1, len(text) // 4)]


class TextLLMWrapper(AbstractLLMWrapper):

    def __init__(self, signals, tts, llmState, modules=None, interface=None):
        super().__init__(signals, tts, llmState, modules, interface)
        self.SYSTEM_PROMPT = SYSTEM_PROMPT
        self.LLM_ENDPOINT = LLM_ENDPOINT
        self.CONTEXT_SIZE = CONTEXT_SIZE
        self.tokenizer = _SimpleTokenizer()

    def prepare_payload(self):
        history = copy.deepcopy(self.signals.history)

        # Build system message: SYSTEM_PROMPT + all module injections (memory, zeitgeist, etc.)
        system_content = self.assemble_injections([Injection(self.SYSTEM_PROMPT, 10)])

        # Context management — drop oldest messages until we fit
        while True:
            messages = [{"role": "system", "content": system_content}] + history
            prompt_tokens = len(self.tokenizer.apply_chat_template(
                messages, tokenize=True, return_tensors="pt"
            )[0])

            if prompt_tokens < 0.9 * self.CONTEXT_SIZE:
                break
            if not history:
                raise RuntimeError("Prompt too long even with no messages")
            history.pop(0)
            self._trace(
                f"prompt too long ({prompt_tokens} tok) — dropping oldest message",
                level="warn",
            )

        # Populate the prompt details viewer
        full_prompt = "═══ SYSTEM ═══\n" + system_content + "\n\n═══ MESSAGES ═══\n"
        for msg in history:
            full_prompt += f"[{msg['role']}] {msg['content']}\n"
        self._trace(
            f"prompt ready: {prompt_tokens} tok / {self.CONTEXT_SIZE} ctx  "
            f"({len(history)} msgs)",
            level="info",
        )
        self.signals.sio_queue.put(("full_prompt", full_prompt))
        self.signals.last_full_prompt = full_prompt

        return {
            "stream": True,
            "mode": "instruct",
            "max_tokens": 200,
            "skip_special_tokens": False,
            "custom_token_bans": BANNED_TOKENS,
            "stop": STOP_STRINGS,
            "messages": messages,
        }
