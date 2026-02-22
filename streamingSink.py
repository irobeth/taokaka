import threading
from discord.sinks import Sink
from pydub import AudioSegment

# How many milliseconds of audio to buffer per user before sending to STT.
# Discord delivers 20ms packets; batching reduces STT choppiness.
_BUFFER_MS = 500
_TARGET_SAMPLE_RATE = 16000
_BUFFER_BYTES = int(_TARGET_SAMPLE_RATE * (_BUFFER_MS / 1000) * 2)  # 16-bit = 2 bytes/sample


class StreamingSink(Sink):
    """Receives per-user PCM audio from a Discord voice channel, converts it
    from 48 kHz stereo to 16 kHz mono, buffers 500 ms worth of audio per user,
    then forwards it to the STT module."""

    def __init__(self, signals, stt, *, filters=None):
        super().__init__(filters=filters)
        self.signals = signals
        self.stt = stt
        self._buffers: dict[int, bytes] = {}
        self._lock = threading.Lock()

    def write(self, data, user):
        # Convert Discord's 48 kHz stereo PCM → 16 kHz mono
        converted = (
            AudioSegment(
                data=data,
                sample_width=2,   # 16-bit
                frame_rate=48000,
                channels=2,
            )
            .set_channels(1)
            .set_frame_rate(_TARGET_SAMPLE_RATE)
            .raw_data
        )

        with self._lock:
            self._buffers[user] = self._buffers.get(user, b"") + converted
            if len(self._buffers[user]) >= _BUFFER_BYTES:
                if self.signals.stt_ready:
                    self.stt.feed_audio(self._buffers[user])
                self._buffers[user] = b""

    def cleanup(self):
        # Flush any remaining buffered audio when recording stops
        with self._lock:
            for user, buf in self._buffers.items():
                if buf and self.signals.stt_ready:
                    self.stt.feed_audio(buf)
            self._buffers.clear()

    def format_audio(self, audio):
        return
