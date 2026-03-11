import logging
import time
import numpy as np
from RealtimeSTT import AudioToTextRecorder
from constants import INPUT_DEVICE_INDEX, STT_VOCABULARY

# Minimum RMS volume (0–1) for a chunk to count as speech. Below = ambient noise.
_MIN_RMS = 0.01
# Minimum word count to accept a transcription (filters "uh", "hmm", sniffs)
_MIN_WORDS = 2


class STT:
    def __init__(self, signals, interface):
        self.recorder = None
        self.signals = signals
        self.interface = interface
        self.API = self.API(self)
        self.enabled = False
        self._recording_start_time = None
        self._peak_rms = 0.0  # peak RMS seen during current recording

    def _on_chunk(self, chunk):
        """Called for every raw audio chunk. Track peak volume for gating."""
        audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms > self._peak_rms:
            self._peak_rms = rms

    def process_text(self, text, speaker=None, source="local"):
        if not self.enabled:
            return
        if self.signals.audio_mode != source:
            return
        if source == "local" and self.signals.AI_speaking:
            self.interface.trace("dropped local STT (AI speaking)", source="STT")
            return

        # Volume gate: reject if peak RMS during recording was too low
        peak = self._peak_rms
        self._peak_rms = 0.0
        if source == "local" and peak < _MIN_RMS:
            self.interface.trace(f"dropped (too quiet, rms={peak:.4f})", source="STT")
            return

        text = text.strip()

        if source == "local" and self._recording_start_time is not None:
            elapsed = time.time() - self._recording_start_time
            self.interface.trace(f"transcription complete ({elapsed:.2f}s, rms={peak:.3f})", source="STT")
            self._recording_start_time = None

        if speaker is None:
            speaker = self.signals.active_voice_user
        attributed = f"{speaker}: {text}" if speaker else text
        self.interface.log(attributed, source="STT")
        self.signals.history.append({"role": "user", "content": attributed, "timestamp": time.time()})

        self.signals.last_message_time = time.time()
        if not self.signals.AI_speaking:
            self.signals.new_message = True

    def recording_start(self):
        self._recording_start_time = time.time()
        self._peak_rms = 0.0
        self.interface.trace("recording started", source="STT")
        self.signals.human_speaking = True

    def recording_stop(self):
        self.interface.trace("recording stopped, transcribing...", source="STT")
        self.signals.human_speaking = False

    def feed_audio(self, data):
        self.recorder.feed_audio(data)

    def listen_loop(self):
        import sounddevice as sd
        try:
            dev = sd.query_devices(INPUT_DEVICE_INDEX)
            self.interface.log(f"Input device [{INPUT_DEVICE_INDEX}]: {dev['name']} (channels={dev['max_input_channels']}, sr={dev['default_samplerate']})", source="STT")
        except Exception as e:
            self.interface.log(f"Input device [{INPUT_DEVICE_INDEX}]: query failed — {e}", source="STT")
        self.interface.log("Starting", source="STT")
        recorder_config = {
            'spinner': False,
            'model': 'deepdml/faster-whisper-large-v3-turbo-ct2',
            'language': 'en',
            'use_microphone': True,
            'input_device_index': INPUT_DEVICE_INDEX,
            'silero_sensitivity': 0.4,
            'silero_use_onnx': True,
            'post_speech_silence_duration': 1.0,
            'min_length_of_recording': 0.5,
            'min_gap_between_recordings': 0.5,
            'enable_realtime_transcription': True,
            'realtime_processing_pause': 0.2,
            'realtime_model_type': 'tiny.en',
            'compute_type': 'auto',
            'initial_prompt': STT_VOCABULARY,
            'on_recording_start': self.recording_start,
            'on_recording_stop': self.recording_stop,
            'on_recorded_chunk': self._on_chunk,
            'level': logging.ERROR
        }

        with AudioToTextRecorder(**recorder_config) as recorder:
            self.recorder = recorder
            self.interface.log("Ready (mic open, STT disabled — press F5 or wait for startup)", source="STT")
            self.signals.stt_ready = True
            while not self.signals.terminate:
                if not self.enabled:
                    time.sleep(0.2)
                    continue
                recorder.text(self.process_text)

    class API:
        def __init__(self, outer):
            self.outer = outer

        def set_STT_status(self, status):
            self.outer.enabled = status
            self.outer.signals.sio_queue.put(('STT_status', status))

        def get_STT_status(self):
            return self.outer.enabled

        def shutdown(self):
            self.outer.recorder.stop()
            self.outer.recorder.interrupt_stop_event.set()
