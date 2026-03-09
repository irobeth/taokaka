from modules.module import Module


class ZeitgeistInjector(Module):

    def __init__(self, signals, enabled=True):
        super().__init__(signals, enabled)
        self.prompt_injection.priority = 155
        self._summary = ""

    def set_summary(self, summary):
        self._summary = summary
        self.signals.zeitgeist = summary

    def get_prompt_injection(self):
        if self._summary:
            self.prompt_injection.text = (
                f"<ZEITGEIST>\n{self._summary}\n</ZEITGEIST>\n"
            )
        else:
            self.prompt_injection.text = ""
        return self.prompt_injection
