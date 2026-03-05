class Comprehension:
    """Base class for response comprehensions.

    A comprehension transforms an LLM response before it reaches TTS.
    The full, unmodified response is always logged and stored in history.
    """

    def process(self, text: str) -> str:
        """Transform the response text. Return the modified text."""
        return text
