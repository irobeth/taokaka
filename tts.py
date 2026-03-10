import os
import time
import tempfile
import threading

import discord
import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import sosfilt, butter

from f5_tts_mlx.generate import generate
from constants import OUTPUT_DEVICE_INDEX, VOICE_REFERENCE, VOICE_REFERENCE_TEXT

_REF_AUDIO_PATH = os.path.join("voices", VOICE_REFERENCE)
_KOKORO_MODEL_PATH = os.path.join("kokoro_models", "kokoro-v1.0.int8.onnx")
_KOKORO_VOICES_PATH = os.path.join("kokoro_models", "voices-v1.0.bin")


class VoiceFX:
    """Audio effects pipeline applied after TTS generation, before playback.

    All parameters can be changed at runtime via signals.voice_fx.
    Set an effect to None/0 to disable it.
    """

    def __init__(self):
        self.pitch_semitones = 0.0   # pitch shift in semitones (positive = higher)
        self.speed = 1.0             # playback speed multiplier (1.0 = normal)
        self.highpass_hz = 0         # high-pass filter cutoff (0 = off)
        self.lowpass_hz = 0          # low-pass filter cutoff (0 = off)
        self.gain_db = 0.0           # volume adjustment in dB

    def process(self, audio, sample_rate):
        """Apply all active effects to audio samples. Returns (audio, sample_rate)."""
        if self.pitch_semitones != 0.0:
            audio, sample_rate = self._pitch_shift(audio, sample_rate)

        if self.speed != 1.0 and self.speed > 0:
            audio, sample_rate = self._speed_change(audio, sample_rate)

        if self.highpass_hz and self.highpass_hz > 0:
            audio = self._highpass(audio, sample_rate)

        if self.lowpass_hz and self.lowpass_hz > 0:
            audio = self._lowpass(audio, sample_rate)

        if self.gain_db != 0.0:
            audio = audio * (10.0 ** (self.gain_db / 20.0))
            audio = np.clip(audio, -1.0, 1.0)

        return audio, sample_rate

    def _pitch_shift(self, audio, sr):
        """Pitch shift by resampling: shift up = shorter signal played at original rate."""
        factor = 2.0 ** (self.pitch_semitones / 12.0)
        indices = np.arange(0, len(audio), factor)
        indices = indices[indices < len(audio)].astype(int)
        return audio[indices], sr

    def _speed_change(self, audio, sr):
        """Change speed by resampling without pitch change."""
        indices = np.arange(0, len(audio), self.speed)
        indices = indices[indices < len(audio)].astype(int)
        return audio[indices], sr

    def _highpass(self, audio, sr):
        sos = butter(4, self.highpass_hz, btype='high', fs=sr, output='sos')
        return sosfilt(sos, audio, axis=0).astype(np.float32)

    def _lowpass(self, audio, sr):
        sos = butter(4, self.lowpass_hz, btype='low', fs=sr, output='sos')
        return sosfilt(sos, audio, axis=0).astype(np.float32)

    @property
    def active(self):
        """True if any effect is enabled."""
        return (self.pitch_semitones != 0.0
                or self.speed != 1.0
                or (self.highpass_hz and self.highpass_hz > 0)
                or (self.lowpass_hz and self.lowpass_hz > 0)
                or self.gain_db != 0.0)


class TTS:
    def __init__(self, signals, interface):
        self.signals = signals
        self.interface = interface
        self.stt = None  # set by main.py after STT is created
        self.enabled = True
        self._stop_event = threading.Event()
        self._active_vc = None
        self._kokoro = None
        self.voice_fx = VoiceFX()
        self.API = self.API(self)

        self.interface.log("Ready", source="TTS")
        self.signals.tts_ready = True

    def play(self, message):
        if not self.enabled or not message.strip():
            return

        self.signals.sio_queue.put(("current_message", message))
        self._stop_event.clear()
        threading.Thread(target=self._generate_and_play, args=(message,), daemon=True).start()

    def _generate_and_play(self, message):
        self.interface.log(message, source="TTS")
        self.signals.AI_speaking = True
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name

            engine = self.signals.tts_engine
            self.interface.trace(f"generate engine={engine} msg={message!r}", source="TTS")
            if engine == "kokoro":
                self._generate_kokoro(message, tmp_path)
            else:
                self._generate_f5(message, tmp_path)

            if self._stop_event.is_set():
                self.interface.trace("stopped before playback", source="TTS", level="warn")
                return

            # Apply voice effects pipeline
            if self.voice_fx.active:
                self.interface.trace("applying voice FX", source="TTS")
                audio, sr = sf.read(tmp_path, dtype="float32")
                audio, sr = self.voice_fx.process(audio, sr)
                sf.write(tmp_path, audio, sr)

            mode = self.signals.audio_mode
            if mode == "local":
                self._mute_local_mic()
                self.interface.trace(f"play → local file={tmp_path}", source="TTS")
                self._play_local(tmp_path)
            elif mode == "discord":
                vc = self.signals.discord_vc
                if vc and vc.is_connected():
                    self.interface.trace(f"play → discord vc={vc.channel.name!r} file={tmp_path}", source="TTS")
                    self._play_discord(vc, tmp_path)
                else:
                    self.interface.trace("discord mode but no vc connected — audio skipped", source="TTS", level="warn")

        except Exception as e:
            self.interface.log(f"error: {e}", source="TTS")
        finally:
            self._unmute_local_mic()
            self.signals.last_message_time = time.time()
            self.signals.AI_speaking = False
            self._active_vc = None
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _generate_f5(self, message, output_path):
        self.interface.trace(f"f5 ref={_REF_AUDIO_PATH!r} out={output_path!r}", source="TTS")
        generate(
            generation_text=message,
            ref_audio_path=_REF_AUDIO_PATH,
            ref_audio_text=VOICE_REFERENCE_TEXT or None,
            output_path=output_path,
        )
        self.interface.trace("f5 generation complete", source="TTS")

    def _generate_kokoro(self, message, output_path):
        if self._kokoro is None:
            self.interface.trace("loading Kokoro model", source="TTS", level="info")
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(_KOKORO_MODEL_PATH, _KOKORO_VOICES_PATH)
        self.interface.trace(f"kokoro voice=af_heart speed=1.0 out={output_path!r}", source="TTS")
        samples, sample_rate = self._kokoro.create(message, voice="af_heart", speed=1.0, lang="en-us")
        self.interface.trace(f"kokoro generated {len(samples)} samples @ {sample_rate}Hz", source="TTS")
        sf.write(output_path, samples, sample_rate)

    def _mute_local_mic(self):
        if self.stt and self.stt.recorder and self.signals.audio_mode == "local":
            self.interface.trace("muting local mic for playback", source="TTS")
            self.stt.recorder.set_microphone(False)

    def _unmute_local_mic(self):
        if self.stt and self.stt.recorder and self.signals.audio_mode == "local":
            self.interface.trace("unmuting local mic", source="TTS")
            self.stt.recorder.set_microphone(True)

    def _play_local(self, tmp_path):
        audio, sr = sf.read(tmp_path, dtype="float32")
        if audio.ndim == 1:
            audio = np.column_stack([audio, audio])  # mono → stereo
        dev_info = sd.query_devices(OUTPUT_DEVICE_INDEX)
        channels = dev_info["max_output_channels"]
        # Match audio channels to device
        if audio.shape[1] > channels:
            audio = audio[:, :channels]
        elif audio.shape[1] < channels:
            audio = np.column_stack([audio] + [audio[:, 0:1]] * (channels - audio.shape[1]))
        chunk_size = 2048
        with sd.OutputStream(samplerate=sr, channels=channels, device=OUTPUT_DEVICE_INDEX) as stream:
            for i in range(0, len(audio), chunk_size):
                if self._stop_event.is_set():
                    break
                chunk = audio[i:i + chunk_size]
                if len(chunk) < chunk_size:
                    chunk = np.pad(chunk, ((0, chunk_size - len(chunk)), (0, 0)))
                stream.write(chunk)

    def _play_discord(self, vc, tmp_path):
        self._active_vc = vc
        done = threading.Event()

        def after(error):
            if error:
                self.interface.log(f"Discord playback error: {error}", source="TTS")
            done.set()

        vc.play(discord.FFmpegPCMAudio(tmp_path), after=after)
        while not done.wait(timeout=0.05):
            if self._stop_event.is_set():
                vc.stop()
                break

    def stop(self):
        self._stop_event.set()
        if self._active_vc and self._active_vc.is_playing():
            self._active_vc.stop()
        self.signals.AI_speaking = False

    class API:
        def __init__(self, outer):
            self.outer = outer

        def set_TTS_status(self, status):
            self.outer.enabled = status
            if not status:
                self.outer.stop()
            self.outer.signals.sio_queue.put(('TTS_status', status))

        def get_TTS_status(self):
            return self.outer.enabled

        def abort_current(self):
            self.outer.stop()
