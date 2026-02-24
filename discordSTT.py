import logging
import threading

from RealtimeSTT import AudioToTextRecorder

log = logging.getLogger(__name__)


class UserRecorder:
    """Per-user RealtimeSTT recorder running in a dedicated background thread."""

    def __init__(self, user_id, display_name, process_text_fn, signals, interface):
        self.user_id = user_id
        self.display_name = display_name
        self.process_text_fn = process_text_fn
        self.signals = signals
        self.interface = interface

        self._buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._ready = False
        self._stop_event = threading.Event()

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
        self._update_status("speaking")

    def _on_recording_stop(self):
        self._update_status("transcribing")

    def _on_text(self, text: str):
        text = text.strip()
        self._update_status("idle")
        if text:
            self.process_text_fn(text, speaker=self.display_name)

    def _run(self):
        self.interface.log(f"Recorder starting for {self.display_name}", source="DiscordSTT")
        try:
            self._recorder = AudioToTextRecorder(
                use_microphone=False,
                spinner=False,
                model='distil-large-v3',
                language='en',
                silero_sensitivity=0.6,
                silero_use_onnx=True,
                post_speech_silence_duration=0.4,
                min_length_of_recording=0,
                min_gap_between_recordings=0.2,
                enable_realtime_transcription=False,
                compute_type='auto',
                on_recording_start=self._on_recording_start,
                on_recording_stop=self._on_recording_stop,
                level=logging.ERROR,
            )
        except Exception:
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
            except Exception:
                if self._stop_event.is_set():
                    break
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
        """Mark as ready. No model pre-loading -- recorders load on demand."""
        if self._ready:
            return
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
