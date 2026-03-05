import copy
import mss, cv2, base64
import numpy as np
from constants import *
from modules.injection import Injection
from llmWrappers.abstractLLMWrapper import AbstractLLMWrapper
from llmWrappers.textLLMWrapper import _SimpleTokenizer


class ImageLLMWrapper(AbstractLLMWrapper):

    def __init__(self, signals, tts, llmState, modules=None, interface=None):
        super().__init__(signals, tts, llmState, modules, interface)
        self.SYSTEM_PROMPT = SYSTEM_PROMPT
        self.LLM_ENDPOINT = MULTIMODAL_ENDPOINT
        self.CONTEXT_SIZE = MULTIMODAL_CONTEXT_SIZE
        self.tokenizer = _SimpleTokenizer()

        self.MSS = None

    def screen_shot(self):
        if self.MSS is None:
            self.MSS = mss.mss()

        # Take a screenshot of the main screen
        frame_bytes = self.MSS.grab(self.MSS.monitors[PRIMARY_MONITOR])

        frame_array = np.array(frame_bytes)
        # resize
        frame_resized = cv2.resize(frame_array, (1920, 1080), interpolation=cv2.INTER_CUBIC)
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 95]
        result, frame_encoded = cv2.imencode('.jpg', frame_resized, encode_param)
        # base64
        frame_base64 = base64.b64encode(frame_encoded).decode("utf-8")
        return frame_base64

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

        # Append screenshot as a user message
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "Here is what's currently on screen."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{self.screen_shot()}"}}
            ]
        })

        # Populate the prompt details viewer
        full_prompt = "═══ SYSTEM ═══\n" + system_content + "\n\n═══ MESSAGES ═══\n"
        for msg in history:
            full_prompt += f"[{msg['role']}] {msg['content']}\n"
        full_prompt += "[user] <screenshot>\n"
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
            "max_tokens": 1000,
            "skip_special_tokens": False,
            "custom_token_bans": BANNED_TOKENS,
            "stop": STOP_STRINGS,
            "messages": messages,
        }
