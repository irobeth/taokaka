import requests
import sseclient
import json
import time
from dotenv import load_dotenv
from constants import *
from modules.injection import Injection
from comprehensions.tts_response_extractor import TTSResponseExtractor
from profanity import ProfanityFilter, SEVERITY_LABELS


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
        self.comprehensions = [TTSResponseExtractor(signals=self.signals)]
        self.profanity_filter = ProfanityFilter(max_severity=2)

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

    def prepare_payload(self):
        raise NotImplementedError("Must implement prepare_payload in child classes")

    def _stream_llm(self, data):
        """Send a request to the LLM and stream the response. Returns (AI_message, raw_events, cancelled)."""
        url = self.LLM_ENDPOINT + "/v1/chat/completions"
        self._trace(
            f"→ POST {url}  max_tokens={data.get('max_tokens')}  "
            f"stop={data.get('stop')}  mode={data.get('mode', 'chat')}",
            level="info",
        )

        stream_response = requests.post(url, headers=self.headers, json=data,
                                        verify=False, stream=True)
        self._trace(f"← HTTP {stream_response.status_code}  streaming…")

        try:
            response_stream = sseclient.SSEClient(stream_response)

            AI_message = ''
            raw_events = []
            for event in response_stream.events():
                raw_events.append(event.data)

                if self.llmState.next_cancelled:
                    continue

                if event.data == "[DONE]":
                    break

                payload = json.loads(event.data)
                chunk = payload['choices'][0]['delta'].get('content') or ''
                if not chunk:
                    continue
                AI_message += chunk
                self.signals.sio_queue.put(("next_chunk", chunk))
                if self.interface:
                    self.interface.stream_token(chunk)
        finally:
            stream_response.close()

        if self.interface:
            self.interface.stream_token("\n")

        # Append raw response bytes to the prompt details viewer
        raw_section = "\n\n═══ RAW RESPONSE ═══\n" + "\n".join(raw_events)
        self.signals.last_full_prompt = self.signals.last_full_prompt + raw_section

        return AI_message, raw_events, self.llmState.next_cancelled

    def _rephrase_prompt(self, data, original_response, violation):
        """Build a re-prompt asking the LLM to rephrase without the offending word."""
        word_id, severity, matched = violation
        max_sev = self.profanity_filter.max_severity
        sev_label = SEVERITY_LABELS.get(severity, str(severity))
        max_label = SEVERITY_LABELS.get(max_sev, str(max_sev))
        rephrase_msg = (
            f"Your previous response was: \"{original_response}\"\n"
            f"This included the word \"{matched}\" which is rated {sev_label} "
            f"(our current rating limit is {max_label}). "
            f"Please rephrase your response without using any words above {max_label} rating. "
            f"Keep the same meaning and tone, just clean it up."
        )
        # Append the rephrase instruction to the existing messages
        new_data = dict(data)
        new_data["messages"] = list(data["messages"]) + [
            {"role": "assistant", "content": original_response},
            {"role": "user", "content": rephrase_msg},
        ]
        return new_data

    def prompt(self):
        if not self.llmState.enabled:
            return

        self.signals.AI_thinking = True
        self.signals.new_message = False
        self.signals.sio_queue.put(("reset_next_message", None))
        if self.interface:
            self.interface._stream_buffer = ""

        data = self.prepare_payload()

        # Prompt loop: retry up to 2 times if profanity filter triggers
        max_retries = 2
        for attempt in range(max_retries + 1):
            AI_message, raw_events, cancelled = self._stream_llm(data)

            if cancelled:
                self._trace("generation cancelled", level="warn")
                self.llmState.next_cancelled = False
                self.signals.sio_queue.put(("reset_next_message", None))
                self.signals.AI_thinking = False
                return

            self._trace(f"response: {len(AI_message)} chars (~{len(AI_message) // 4} tok)  raw events: {len(raw_events)}")

            # Strip echoed prompt prefix
            ai_prefix = AI_NAME + ": "
            if ai_prefix in AI_message:
                AI_message = AI_message.rsplit(ai_prefix, 1)[-1].strip()
                self._trace(f"stripped echo prefix → {len(AI_message)} chars remaining")

            # Separate thinking from spoken response
            thinking_text = ""
            spoken_message = AI_message
            if "</think>" in AI_message:
                parts = AI_message.split("</think>", 1)
                thinking_text = parts[0].replace("<think>", "").strip()
                spoken_message = parts[1].strip()

            if thinking_text:
                self.signals.recent_thoughts = (
                    self.signals.recent_thoughts + [{"thought": thinking_text, "timestamp": time.time()}]
                )[-20:]

            # Check profanity severity (sync from signals in case it was changed)
            self.profanity_filter.max_severity = self.signals.max_profanity_severity
            violation = self.profanity_filter.worst_violation(spoken_message)
            if violation and attempt < max_retries:
                word_id, severity, matched = violation
                sev_label = SEVERITY_LABELS.get(severity, str(severity))
                max_label = SEVERITY_LABELS.get(self.profanity_filter.max_severity, str(self.profanity_filter.max_severity))
                self._trace(
                    f"profanity filter: \"{matched}\" ({sev_label}) exceeds rating {max_label}, re-prompting (attempt {attempt + 1})",
                    level="warn",
                )
                self.signals.sio_queue.put(("reset_next_message", None))
                data = self._rephrase_prompt(data, spoken_message, violation)
                continue

            # Passed filter (or exhausted retries)
            break

        if self.interface:
            self.interface.log(spoken_message, source="AI")
        else:
            print("AI OUTPUT: " + spoken_message)
        self.signals.last_message_time = time.time()
        self.signals.AI_speaking = True
        self.signals.AI_thinking = False

        # Hard blacklist filter (replaces entire message)
        if self.is_filtered(spoken_message):
            spoken_message = "Filtered."
            self.signals.sio_queue.put(("reset_next_message", None))
            self.signals.sio_queue.put(("next_chunk", "Filtered."))

        self.signals.history.append({"role": "assistant", "content": spoken_message, "timestamp": time.time()})

        tts_message = spoken_message
        for comp in self.comprehensions:
            tts_message = comp.process(tts_message)
            if not tts_message:
                break
        if tts_message:
            self.tts.play(tts_message)

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
