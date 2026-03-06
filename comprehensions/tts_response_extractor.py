import re

from comprehensions.base import Comprehension

# Matches emoji and other non-speakable unicode: emoticons, dingbats, symbols, flags, etc.
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # misc symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess, extended-A
    "\U0001FA70-\U0001FAFF"  # extended-B
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U000020E3"             # combining enclosing keycap
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002300-\U000023FF"  # misc technical
    "\U0000203C-\U00003299"  # CJK symbols, enclosed chars
    "]+",
    flags=re.UNICODE,
)


class TTSResponseExtractor(Comprehension):
    """Extracts the spoken portion of an LLM response by splitting on </think>.

    Everything after the last </think> tag is treated as the spoken response.
    If no </think> is present, the full text is returned as-is.
    Emojis and non-speakable unicode are stripped before TTS.
    """

    def process(self, text: str) -> str:
        if "</think>" in text:
            text = text.rsplit("</think>", 1)[-1]
        text = _EMOJI_RE.sub("", text)
        # Collapse any leftover double spaces from stripped emojis
        text = re.sub(r"  +", " ", text)
        return text.strip()
