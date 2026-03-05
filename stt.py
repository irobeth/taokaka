import logging
import time
from RealtimeSTT import AudioToTextRecorder
from constants import INPUT_DEVICE_INDEX


class STT:
    def __init__(self, signals, interface):
        self.recorder = None
        self.signals = signals
        self.interface = interface
        self.API = self.API(self)
        self.enabled = True
        self._recording_start_time = None

    def process_text(self, text, speaker=None, source="local"):
        if not self.enabled:
            return
        if self.signals.audio_mode != source:
            return
        if source == "local" and self.signals.AI_speaking:
            self.interface.trace("dropped local STT (AI speaking)", source="STT")
            return

        if source == "local" and self._recording_start_time is not None:
            elapsed = time.time() - self._recording_start_time
            self.interface.trace(f"transcription complete ({elapsed:.2f}s)", source="STT")
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
        self.interface.trace("recording started", source="STT")
        self.signals.human_speaking = True

    def recording_stop(self):
        self.interface.trace("recording stopped, transcribing...", source="STT")
        self.signals.human_speaking = False

    def feed_audio(self, data):
        self.recorder.feed_audio(data)

    def listen_loop(self):
        self.interface.log("Starting", source="STT")
        recorder_config = {
            'spinner': False,
            'model': 'deepdml/faster-whisper-large-v3-turbo-ct2',
            'language': 'en',
            'use_microphone': True,
            'input_device_index': INPUT_DEVICE_INDEX,
            'silero_sensitivity': 0.6,
            'silero_use_onnx': True,
            'post_speech_silence_duration': 0.4,
            'min_length_of_recording': 0,
            'min_gap_between_recordings': 0.2,
            'enable_realtime_transcription': True,
            'realtime_processing_pause': 0.2,
            'realtime_model_type': 'tiny.en',
            'compute_type': 'auto',
            'on_recording_start': self.recording_start,
            'on_recording_stop': self.recording_stop,
            'level': logging.ERROR
        }

        with AudioToTextRecorder(**recorder_config) as recorder:
            self.recorder = recorder
            self.interface.log("Ready", source="STT")
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
