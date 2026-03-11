from modules.module import Module


class MoodInjector(Module):
    """Injects Taokaka's current emotional state into the LLM prompt,
    including overall mood and any notable per-subject feelings."""

    def __init__(self, signals, enabled=True):
        super().__init__(signals, enabled)
        self.prompt_injection.priority = 158  # just after zeitgeist (155)

    def get_prompt_injection(self):
        mood = self.signals.extractor_signals.get("mood", {})
        emotion = mood.get("emotion")
        if not emotion:
            self.prompt_injection.text = ""
            return self.prompt_injection

        intensity = mood.get("intensity", 0.5)
        summary = mood.get("summary", "")
        shift = mood.get("shift", "")

        # Intensity descriptors
        if intensity >= 0.8:
            strength = "overwhelmingly"
        elif intensity >= 0.6:
            strength = "strongly"
        elif intensity >= 0.4:
            strength = "somewhat"
        elif intensity >= 0.2:
            strength = "mildly"
        else:
            strength = "faintly"

        emoji = mood.get("emoji", "")
        text = f"<MOOD>\n{emoji} Taokaka {strength} feels {emotion}."
        if summary:
            text += f" {summary}"
        if shift:
            text += f"\nHowever, {shift.lower()}"

        # Inject notable subject moods
        subject_moods = self.signals.extractor_signals.get("subject_moods", {})
        if subject_moods:
            text += "\n\nFeelings about specific subjects:"
            for name, sm in subject_moods.items():
                em = sm.get("emotion", "")
                si = sm.get("intensity", 0)
                reason = sm.get("reason", "")
                if em and si >= 0.3:  # only inject notable feelings
                    emj = sm.get("emoji", "")
                    text += f"\n- {emj} {name}: {em}"
                    if reason:
                        text += f" — {reason}"

        text += "\n</MOOD>\n"
        self.prompt_injection.text = text
        return self.prompt_injection
