import time


class Prompter:
    def __init__(self, signals, llms, modules=None, interface=None):
        self.signals = signals
        self.llms = llms
        self.interface = interface
        if modules is None:
            self.modules = {}
        else:
            self.modules = modules

        self.system_ready = False
        self.timeSinceLastMessage = 0.0

    def _log(self, msg):
        if self.interface:
            self.interface.log(msg, source="Prompter")
        else:
            print(msg)

    def prompt_now(self):
        # Don't prompt AI if system isn't ready yet
        if not self.signals.stt_ready or not self.signals.tts_ready:
            return False
        # Don't prompt AI when anyone is currently talking
        if self.signals.human_speaking or self.signals.AI_thinking or self.signals.AI_speaking:
            return False
        # Prompt AI if human said something
        if self.signals.new_message:
            return True
        # Prompt AI if there are unprocessed chat messages
        if len(self.signals.recentTwitchMessages) > 0:
            return True
        # Prompt if some amount of seconds has passed without anyone talking
        if self.timeSinceLastMessage > self.signals.patience:
            return True

    def chooseLLM(self):
        if "multimodal" in self.modules and self.modules["multimodal"].API.multimodal_now():
            return self.llms["image"]
        else:
            return self.llms["text"]

    def prompt_loop(self):
        self._log("Prompter loop started")

        while not self.signals.terminate:
            # Set lastMessageTime to now if program is still starting
            if self.signals.last_message_time == 0.0 or (not self.signals.stt_ready or not self.signals.tts_ready):
                self.signals.last_message_time = time.time()
                self.timeSinceLastMessage = 0.0
            else:
                if not self.system_ready:
                    self._log("SYSTEM READY")
                    self.system_ready = True

            # Calculate and set time since last message
            self.timeSinceLastMessage = time.time() - self.signals.last_message_time
            self.signals.sio_queue.put(("patience_update", {"crr_time": self.timeSinceLastMessage, "total_time": self.signals.patience}))

            # Decide and prompt LLM
            if self.prompt_now():
                self._log("PROMPTING AI")
                llmWrapper = self.chooseLLM()
                llmWrapper.prompt()
                self.signals.last_message_time = time.time()
                # Signal that a prompt cycle completed (for curiosity generation)
                self.signals.extractor_signals["prompt_completed"] = time.time()

            # Sleep for 0.1 seconds before checking again.
            time.sleep(0.1)
