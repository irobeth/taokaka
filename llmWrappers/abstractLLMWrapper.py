import copy
import requests
import sseclient
import json
import time
from dotenv import load_dotenv
from constants import *
from modules.injection import Injection


class AbstractLLMWrapper:

    def __init__(self, signals, tts, llmState, modules=None, interface=None):
        self.signals = signals
        self.llmState = llmState
        self.tts = tts
        self.interface = interface
        self.API = self.API(self)
        if modules is None:
            self.modules = {}
        else:
            self.modules = modules

        self.headers = {"Content-Type": "application/json"}

        load_dotenv()

        #Below constants must be set by child classes
        self.SYSTEM_PROMPT = None
        self.LLM_ENDPOINT = None
        self.CONTEXT_SIZE = None
        self.tokenizer = None

    # Basic filter to check if a message contains a word in the blacklist
    def is_filtered(self, text):
        # Filter messages with words in blacklist
        if any(bad_word.lower() in text.lower().split() for bad_word in self.llmState.blacklist):
            return True
        else:
            return False

    # Assembles all the injections from all modules into a single prompt by increasing priority
    def assemble_injections(self, injections=None):
        if injections is None:
            injections = []

        # Gather all injections from all modules
        for module in self.modules.values():
            injections.append(module.get_prompt_injection())

        # Let all modules clean up once the prompt injection has been fetched from all modules
        for module in self.modules.values():
            module.cleanup()

        # Sort injections by priority
        injections = sorted(injections, key=lambda x: x.priority)

        # Assemble injections
        prompt = ""
        for injection in injections:
            prompt += injection.text

        prompt += SYSTEM_PROMPT_FOOTER

        return prompt

    def _trace(self, msg, level="debug"):
        if self.interface:
            self.interface.trace(msg, source="LLM", level=level)

    def generate_prompt(self):
        messages = copy.deepcopy(self.signals.history)

        # For every message prefix with speaker name unless it is blank
        for message in messages:
            if message["role"] == "user" and message["content"] != "":
                message["content"] = HOST_NAME + ": " + message["content"] + "\n"
            elif message["role"] == "assistant" and message["content"] != "":
                message["content"] = AI_NAME + ": " + message["content"] + "\n"

        while True:
            chat_section = ""
            for message in messages:
                chat_section += message["content"]

            generation_prompt = AI_NAME + ": "

            base_injections = [Injection(self.SYSTEM_PROMPT, 10), Injection(chat_section, 100)]
            full_prompt = self.assemble_injections(base_injections) + generation_prompt
            wrapper = [{"role": "user", "content": full_prompt}]

            # Find out roughly how many tokens the prompt is
            # Not 100% accurate, but it should be a good enough estimate
            prompt_tokens = len(self.tokenizer.apply_chat_template(wrapper, tokenize=True, return_tensors="pt")[0])

            # Maximum 90% context size usage before prompting LLM
            if prompt_tokens < 0.9 * self.CONTEXT_SIZE:
                self._trace(
                    f"prompt ready: {prompt_tokens} tok / {self.CONTEXT_SIZE} ctx  "
                    f"({len(messages)} msgs, {len(full_prompt)} chars)",
                    level="info",
                )
                self.signals.sio_queue.put(("full_prompt", full_prompt))
                self.signals.last_full_prompt = full_prompt
                return full_prompt
            else:
                # If the prompt is too long even with no messages, there's nothing we can do, crash
                if len(messages) < 1:
                    raise RuntimeError("Prompt too long even with no messages")

                # Remove the oldest message from the prompt and try again
                messages.pop(0)
                self._trace(f"prompt too long ({prompt_tokens} tok) — dropping oldest message", level="warn")
                if not self.interface:
                    print("Prompt too long, removing earliest message")

    def prepare_payload(self):
        raise NotImplementedError("Must implement prepare_payload in child classes")

    def prompt(self):
        if not self.llmState.enabled:
            return

        self.signals.AI_thinking = True
        self.signals.new_message = False
        self.signals.sio_queue.put(("reset_next_message", None))

        data = self.prepare_payload()

        url = self.LLM_ENDPOINT + "/v1/chat/completions"
        self._trace(
            f"→ POST {url}  max_tokens={data.get('max_tokens')}  "
            f"stop={data.get('stop')}  mode={data.get('mode', 'chat')}",
            level="info",
        )

        stream_response = requests.post(url, headers=self.headers, json=data,
                                        verify=False, stream=True)
        self._trace(f"← HTTP {stream_response.status_code}  streaming…")
        response_stream = sseclient.SSEClient(stream_response)

        AI_message = ''
        raw_events = []
        for event in response_stream.events():
            raw_events.append(event.data)

            # Check to see if next message was canceled
            if self.llmState.next_cancelled:
                continue

            # Standard OpenAI streaming terminator (sent by LM Studio and others)
            if event.data == "[DONE]":
                break

            payload = json.loads(event.data)
            chunk = payload['choices'][0]['delta'].get('content') or ''
            if not chunk:
                continue
            AI_message += chunk
            self.signals.sio_queue.put(("next_chunk", chunk))

        # Append raw response bytes to the prompt details viewer
        raw_section = "\n\n═══ RAW RESPONSE ═══\n" + "\n".join(raw_events)
        self.signals.last_full_prompt += raw_section

        if self.llmState.next_cancelled:
            self._trace("generation cancelled", level="warn")
            self.llmState.next_cancelled = False
            self.signals.sio_queue.put(("reset_next_message", None))
            self.signals.AI_thinking = False
            return

        self._trace(f"response: {len(AI_message)} chars (~{len(AI_message) // 4} tok)  raw events: {len(raw_events)}")

        # If the model echoed the prompt back, strip everything before the last
        # "Taokaka: " prefix so we only speak the actual response.
        ai_prefix = AI_NAME + ": "
        if ai_prefix in AI_message:
            AI_message = AI_message.rsplit(ai_prefix, 1)[-1].strip()
            self._trace(f"stripped echo prefix → {len(AI_message)} chars remaining")

        if self.interface:
            self.interface.log(AI_message, source="AI")
        else:
            print("AI OUTPUT: " + AI_message)
        self.signals.last_message_time = time.time()
        self.signals.AI_speaking = True
        self.signals.AI_thinking = False

        if self.is_filtered(AI_message):
            AI_message = "Filtered."
            self.signals.sio_queue.put(("reset_next_message", None))
            self.signals.sio_queue.put(("next_chunk", "Filtered."))

        self.signals.history.append({"role": "assistant", "content": AI_message, "timestamp": time.time()})
        self.tts.play(AI_message)

    class API:
        def __init__(self, outer):
            self.outer = outer

        def get_blacklist(self):
            return self.outer.llmState.blacklist

        def set_blacklist(self, new_blacklist):
            self.outer.llmState.blacklist = new_blacklist
            with open('blacklist.txt', 'w') as file:
                for word in new_blacklist:
                    file.write(word + "\n")

            # Notify clients
            self.outer.signals.sio_queue.put(('get_blacklist', new_blacklist))

        def set_LLM_status(self, status):
            self.outer.llmState.enabled = status
            if status:
                self.outer.signals.AI_thinking = False
            self.outer.signals.sio_queue.put(('LLM_status', status))

        def get_LLM_status(self):
            return self.outer.llmState.enabled

        def cancel_next(self):
            self.outer.llmState.next_cancelled = True
            # For text-generation-webui: Immediately stop generation
            requests.post(self.outer.LLM_ENDPOINT + "/v1/internal/stop-generation", headers={"Content-Type": "application/json"})
