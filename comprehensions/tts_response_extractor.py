from comprehensions.base import Comprehension


class TTSResponseExtractor(Comprehension):
    """Extracts the spoken portion of an LLM response by splitting on </think>.

    Everything after the last </think> tag is treated as the spoken response.
    If no </think> is present, the full text is returned as-is.
    """

    def process(self, text: str) -> str:
        if "</think>" in text:
            return text.rsplit("</think>", 1)[-1].strip()
        return text.strip()
