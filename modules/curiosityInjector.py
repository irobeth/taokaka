from constants import AI_NAME
from modules.module import Module


class CuriosityInjector(Module):
    """Injects active curiosities into the LLM prompt so Taokaka is aware
    of what she's currently interested in and can steer conversation accordingly."""

    def __init__(self, signals, enabled=True):
        super().__init__(signals, enabled)
        self.prompt_injection.priority = 65  # just after memories (60), before personality

    def get_prompt_injection(self):
        curiosities = self.signals.extractor_signals.get("curiosities", [])
        if curiosities:
            text = f"[Curiosities]\n{AI_NAME} is currently curious about:\n"
            for c in curiosities[:5]:  # cap at 5 to avoid bloating the prompt
                text += f"- {c}\n"
            text += (
                f"If relevant, {AI_NAME} might naturally bring up or follow up on these interests. "
                f"Don't force it — only if it fits the flow.\n"
                f"[/Curiosities]\n"
            )
            self.prompt_injection.text = text
        else:
            self.prompt_injection.text = ""
        return self.prompt_injection
