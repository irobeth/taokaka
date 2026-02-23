from discord.sinks import Sink
from pydub import AudioSegment

_TARGET_SAMPLE_RATE = 16000


class StreamingSink(Sink):
    """Receives per-user PCM audio from a Discord voice channel, converts it
    from 48 kHz stereo to 16 kHz mono, then forwards it to DiscordSTT with
    speaker identity attached."""

    def __init__(self, signals, discord_stt, *, filters=None):
        super().__init__(filters=filters)
        self.signals = signals
        self.discord_stt = discord_stt
        self._name_cache: dict[int, str] = {}

    def _resolve_name(self, user_id: int) -> str:
        if user_id in self._name_cache:
            return self._name_cache[user_id]

        member = (
            next((m for m in self.vc.channel.members if m.id == user_id), None)
            or self.vc.guild.get_member(user_id)
        )
        name = member.display_name if member else str(user_id)
        self._name_cache[user_id] = name
        return name

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

        display_name = self._resolve_name(user)
        self.discord_stt.feed_audio(converted, user, display_name)

    def cleanup(self):
        self.discord_stt.cleanup()

    def format_audio(self, audio):
        return
