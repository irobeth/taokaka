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

# Matches {me}...{/me} emote tags
_EMOTE_RE = re.compile(r"\{me\}(.*?)\{/me\}", flags=re.DOTALL)

# Matches *asterisk emotes* as fallback
_ASTERISK_EMOTE_RE = re.compile(r"\*([^*]+)\*")

# Matches {nick user="username"}Nickname{/nick} tags
_NICK_RE = re.compile(r'\{nick user="([^"]+)"\}(.*?)\{/nick\}', flags=re.DOTALL)


class TTSResponseExtractor(Comprehension):
    """Extracts the spoken portion of an LLM response.

    - Splits on </think> to remove reasoning
    - Extracts {me}...{/me} emotes into signals for vtuber control
    - Falls back to stripping *asterisk emotes* too
    - Strips emoji and non-speakable unicode before TTS
    """

    def __init__(self, signals=None):
        self.signals = signals

    def process(self, text: str) -> str:
        if "</think>" in text:
            text = text.rsplit("</think>", 1)[-1]

        # Extract {me}...{/me} emotes
        emotes = _EMOTE_RE.findall(text)
        text = _EMOTE_RE.sub("", text)

        # Also strip *asterisk emotes* as fallback
        asterisk_emotes = _ASTERISK_EMOTE_RE.findall(text)
        text = _ASTERISK_EMOTE_RE.sub("", text)

        emotes.extend(asterisk_emotes)

        # Publish emotes to signals for vtuber/animation layer
        if self.signals is not None and emotes:
            self.signals.extractor_signals["emotes"] = [e.strip() for e in emotes]

        # Extract {nick user="username"}Nickname{/nick} tags
        nicknames = _NICK_RE.findall(text)  # list of (user, nickname) tuples
        text = _NICK_RE.sub(r"\2", text)  # replace tag with just the nickname text

        if self.signals is not None and nicknames:
            pending = self.signals.extractor_signals.get("pending_nicknames", [])
            for user, nick in nicknames:
                pending.append({"user": user.strip(), "nickname": nick.strip()})
            self.signals.extractor_signals["pending_nicknames"] = pending

        text = _EMOJI_RE.sub("", text)
        # Collapse any leftover double spaces from stripped content
        text = re.sub(r"  +", " ", text)
        return text.strip()
