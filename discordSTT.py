import logging
import threading
import time

from faster_whisper import WhisperModel
from RealtimeSTT import AudioToTextRecorder
from constants import STT_VOCABULARY

log = logging.getLogger(__name__)


class UserRecorder:
    """Per-user RealtimeSTT recorder running in a dedicated background thread."""

    def __init__(self, user_id, display_name, process_text_fn, signals, interface,
                 shared_realtime_model=None):
        self.user_id = user_id
        self.display_name = display_name
        self.process_text_fn = process_text_fn
        self.signals = signals
        self.interface = interface
        self._shared_realtime_model = shared_realtime_model

        self._buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._ready = False
        self._stop_event = threading.Event()
        self._recording_start_time = None

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"discord-stt-{display_name}",
        )
        self._thread.start()

    def feed(self, data: bytes):
        """Buffer audio until recorder is ready, then feed directly."""
        if self._stop_event.is_set():
            return
        if self._ready:
            self._recorder.feed_audio(data)
        else:
            with self._buffer_lock:
                self._buffer.extend(data)

    def _update_status(self, status: str):
        workers = self.signals.stt_workers
        for entry in workers:
            if entry["name"] == self.display_name:
                entry["status"] = status
                return

    def _on_recording_start(self):
        self._recording_start_time = time.time()
        self.interface.trace(f"{self.display_name} recording started", source="DiscordSTT")
        self._update_status("speaking")

    def _on_recording_stop(self):
        self.interface.trace(f"{self.display_name} recording stopped, transcribing...", source="DiscordSTT")
        self._update_status("transcribing")

    def _on_text(self, text: str):
        text = text.strip()
        if text and self._recording_start_time is not None:
            elapsed = time.time() - self._recording_start_time
            self.interface.trace(f"{self.display_name} transcription complete ({elapsed:.2f}s)", source="DiscordSTT")
        self._recording_start_time = None
        self._update_status("idle")
        if text:
            self.process_text_fn(text, speaker=self.display_name)

    def _run(self):
        self.interface.log(f"Recorder starting for {self.display_name}", source="DiscordSTT")
        try:
            recorder_kwargs = dict(
                use_microphone=False,
                spinner=False,
                model='deepdml/faster-whisper-large-v3-turbo-ct2',
                language='en',
                silero_sensitivity=0.6,
                silero_use_onnx=True,
                post_speech_silence_duration=0.4,
                min_length_of_recording=0,
                min_gap_between_recordings=0.2,
                enable_realtime_transcription=True,
                realtime_model_type='tiny.en',
                realtime_processing_pause=0.2,
                compute_type='auto',
                initial_prompt=STT_VOCABULARY,
                on_recording_start=self._on_recording_start,
                on_recording_stop=self._on_recording_stop,
                level=logging.ERROR,
            )
            self._recorder = AudioToTextRecorder(**recorder_kwargs)
            # Replace the per-recorder model with the shared instance
            if self._shared_realtime_model is not None:
                self._recorder.realtime_model_type = self._shared_realtime_model
        except Exception as exc:
            self.interface.trace(
                f"Failed to create recorder for {self.display_name}: {exc}",
                source="DiscordSTT", level="error",
            )
            log.exception("Failed to create recorder for %s", self.display_name)
            return

        # Flush buffered audio
        with self._buffer_lock:
            if self._buffer:
                self._recorder.feed_audio(bytes(self._buffer))
                self._buffer.clear()
            self._ready = True

        self.interface.log(f"Recorder ready for {self.display_name}", source="DiscordSTT")

        # Block on text() until stop() interrupts
        while not self._stop_event.is_set():
            try:
                self._recorder.text(self._on_text)
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                self.interface.trace(
                    f"Recorder error for {self.display_name}: {exc}",
                    source="DiscordSTT", level="error",
                )
                log.exception("Recorder error for %s", self.display_name)

    def stop(self):
        self._stop_event.set()
        if self._ready:
            try:
                self._recorder.stop()
                self._recorder.interrupt_stop_event.set()
            except Exception:
                pass


class DiscordSTT:
    """Manages per-user RealtimeSTT recorders for Discord voice."""

    def __init__(self, signals, interface, process_text_fn):
        self.signals = signals
        self.interface = interface
        self.process_text_fn = process_text_fn

        self._recorders: dict[int, UserRecorder] = {}
        self._lock = threading.Lock()
        self._ready = False

    def init_model(self):
        """Pre-load shared realtime model and mark as ready."""
        if self._ready:
            return
        self.interface.log("Loading shared realtime model (tiny.en)...", source="DiscordSTT")
        self._shared_realtime_model = WhisperModel('tiny.en', compute_type='auto')
        self._ready = True
        self.signals.stt_workers = []
        self.interface.log("Discord STT ready.", source="DiscordSTT")

    def feed_audio(self, data: bytes, user_id: int, display_name: str):
        """Forward 16 kHz mono PCM to the user's recorder, creating it if needed."""
        if not self._ready:
            return

        with self._lock:
            recorder = self._recorders.get(user_id)
            if recorder is None:
                recorder = UserRecorder(
                    user_id, display_name,
                    self.process_text_fn, self.signals, self.interface,
                    shared_realtime_model=self._shared_realtime_model,
                )
                self._recorders[user_id] = recorder
                self.signals.stt_workers.append({"name": display_name, "status": "idle"})

        recorder.feed(data)

    def cleanup(self):
        """Stop all recorders (e.g. on /stop)."""
        with self._lock:
            for recorder in self._recorders.values():
                recorder.stop()
            self._recorders.clear()
        self.signals.stt_workers = []

    def shutdown(self):
        """Full teardown."""
        self.cleanup()
        self._ready = False
