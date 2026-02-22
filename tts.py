import os
import time
import tempfile
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf

from f5_tts_mlx.generate import generate
from constants import OUTPUT_DEVICE_INDEX, VOICE_REFERENCE, VOICE_REFERENCE_TEXT

_REF_AUDIO_PATH = os.path.join("voices", VOICE_REFERENCE)


class TTS:
    def __init__(self, signals):
        self.signals = signals
        self.enabled = True
        self._stop_event = threading.Event()
        self.API = self.API(self)

        print("TTS Ready")
        self.signals.tts_ready = True

    def play(self, message):
        if not self.enabled or not message.strip():
            return

        self.signals.sio_queue.put(("current_message", message))
        self._stop_event.clear()
        threading.Thread(target=self._generate_and_play, args=(message,), daemon=True).start()

    def _generate_and_play(self, message):
        self.signals.AI_speaking = True
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name

            generate(
                generation_text=message,
                ref_audio_path=_REF_AUDIO_PATH,
                ref_audio_text=VOICE_REFERENCE_TEXT or None,
                output_path=tmp_path,
            )

            audio, sr = sf.read(tmp_path, dtype="float32")
            if audio.ndim > 1:
                audio = audio[:, 0]  # take first channel if stereo

            chunk_size = 2048
            with sd.OutputStream(samplerate=sr, channels=1, device=OUTPUT_DEVICE_INDEX) as stream:
                for i in range(0, len(audio), chunk_size):
                    if self._stop_event.is_set():
                        break
                    chunk = audio[i:i + chunk_size]
                    # Pad the final chunk to avoid PortAudio underrun
                    if len(chunk) < chunk_size:
                        chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
                    stream.write(chunk.reshape(-1, 1))

        except Exception as e:
            print(f"TTS error: {e}")
        finally:
            self.signals.last_message_time = time.time()
            self.signals.AI_speaking = False
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def stop(self):
        self._stop_event.set()
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
