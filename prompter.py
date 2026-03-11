import time


# Patience per alertness state (seconds of silence before self-prompting)
_PATIENCE_AWAKE = 15       # active conversation — quick follow-ups
_PATIENCE_NAPPING = 90     # idle — occasional check-ins
# asleep = never self-prompts

# Time thresholds for state transitions (seconds since last activity)
_AWAKE_TO_NAPPING = 120    # 2 minutes idle → napping
_NAPPING_TO_ASLEEP = 600   # 10 minutes idle → asleep


class Prompter:
    def __init__(self, signals, llms, modules=None, interface=None, tts=None):
        self.signals = signals
        self.llms = llms
        self.tts = tts
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

    def _update_alertness(self):
        """State machine: awake ↔ napping → asleep. Activity wakes her up."""
        old = self.signals.alertness
        idle = self.timeSinceLastMessage
        has_activity = (
            self.signals.new_message
            or self.signals.human_speaking
            or len(self.signals.recentTwitchMessages) > 0
        )

        if has_activity:
            # Any input wakes Tao up
            if old != "awake":
                self.signals.alertness = "awake"
                self._log("*yawns* Tao is awake!")
            return

        # No activity — decay based on idle time
        if old == "awake" and idle > _AWAKE_TO_NAPPING:
            self.signals.alertness = "napping"
            self._log("Tao is napping... zzz")
        elif old == "napping" and idle > _NAPPING_TO_ASLEEP:
            self.signals.alertness = "asleep"
            self._log("Tao fell asleep! (send a message to wake her)")

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

        # Self-prompt based on alertness state
        state = self.signals.alertness
        if state == "awake":
            return self.timeSinceLastMessage > _PATIENCE_AWAKE
        elif state == "napping":
            return self.timeSinceLastMessage > _PATIENCE_NAPPING
        else:  # asleep
            return False

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
                    if self.tts:
                        self.tts.play("TAOKAKA ZOOM!!", blocking=True)
                    self._log("SYSTEM READY")
                    self.system_ready = True

            # Calculate and set time since last message
            # Freeze idle timer while Tao is thinking or speaking
            if self.signals.AI_thinking or self.signals.AI_speaking:
                self.signals.last_message_time = time.time()
            self.timeSinceLastMessage = time.time() - self.signals.last_message_time
            self.signals.sio_queue.put(("patience_update", {"crr_time": self.timeSinceLastMessage, "total_time": self.signals.patience}))

            # Update alertness state machine
            self._update_alertness()

            # Decide and prompt LLM
            if self.prompt_now():
                self._log("PROMPTING AI")
                # Prompting means she's active
                if self.signals.alertness != "awake":
                    self.signals.alertness = "awake"
                llmWrapper = self.chooseLLM()
                llmWrapper.prompt()
                self.signals.last_message_time = time.time()
                # Signal that a prompt cycle completed (for curiosity generation)
                self.signals.extractor_signals["prompt_completed"] = time.time()

            # Sleep for 0.1 seconds before checking again.
            time.sleep(0.1)
