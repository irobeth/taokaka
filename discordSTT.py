import logging
import threading
import queue
import numpy as np
import torch

log = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
# Silero VAD operates on fixed-size chunks; 512 samples @ 16kHz = 32ms
_VAD_CHUNK_SAMPLES = 512
_VAD_CHUNK_BYTES = _VAD_CHUNK_SAMPLES * 2  # 16-bit PCM

# Speech detection thresholds
_SPEECH_THRESHOLD = 0.5
_SILENCE_DURATION_S = 0.6   # seconds of silence before end-of-speech
_MIN_SPEECH_DURATION_S = 0.3  # ignore utterances shorter than this

_SILENCE_CHUNKS = int(_SILENCE_DURATION_S * _SAMPLE_RATE / _VAD_CHUNK_SAMPLES)
_MIN_SPEECH_CHUNKS = int(_MIN_SPEECH_DURATION_S * _SAMPLE_RATE / _VAD_CHUNK_SAMPLES)


class UserVoicePipeline:
    """Per-user VAD state: Silero model instance, audio buffer, speech tracking."""

    def __init__(self):
        self.vad_model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            onnx=True,
            trust_repo=True,
        )
        self.audio_buffer = b""      # raw PCM waiting for VAD chunk alignment
        self.speech_audio = b""      # accumulated speech audio for transcription
        self.is_speaking = False
        self.silence_chunks = 0      # consecutive silent chunks since last speech
        self.speech_chunks = 0       # total speech chunks in current utterance

    def reset_vad_state(self):
        self.vad_model.reset_states()
        self.speech_audio = b""
        self.is_speaking = False
        self.silence_chunks = 0
        self.speech_chunks = 0


class DiscordSTT:
    """Manages per-user voice pipelines with a shared Whisper model for transcription."""

    def __init__(self, signals, interface, process_text_fn):
        self.signals = signals
        self.interface = interface
        self.process_text_fn = process_text_fn

        self._pipelines: dict[int, UserVoicePipeline] = {}
        self._pipeline_lock = threading.Lock()

        self._whisper_model = None
        self._whisper_lock = threading.Lock()

        self._queue: queue.Queue = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()

    def init_model(self):
        """Load the shared Whisper model and start the transcription worker."""
        if self._whisper_model is not None:
            return

        from faster_whisper import WhisperModel

        self.interface.log("Loading Whisper model for Discord STT…", source="DiscordSTT")
        self._whisper_model = WhisperModel(
            "distil-large-v3",
            device="auto",
            compute_type="auto",
        )
        self.interface.log("Whisper model ready.", source="DiscordSTT")

        self._shutdown_event.clear()
        self._worker_thread = threading.Thread(
            target=self._transcription_worker,
            daemon=True,
            name="discord-stt-worker",
        )
        self._worker_thread.start()

    def feed_audio(self, data: bytes, user_id: int, display_name: str):
        """Feed 16kHz mono PCM audio for a specific user. Runs VAD inline."""
        pipeline = self._get_pipeline(user_id)

        pipeline.audio_buffer += data

        # Process all complete VAD chunks
        while len(pipeline.audio_buffer) >= _VAD_CHUNK_BYTES:
            chunk = pipeline.audio_buffer[:_VAD_CHUNK_BYTES]
            pipeline.audio_buffer = pipeline.audio_buffer[_VAD_CHUNK_BYTES:]

            # Run Silero VAD on chunk
            audio_float = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            audio_tensor = torch.from_numpy(audio_float)
            speech_prob = pipeline.vad_model(audio_tensor, _SAMPLE_RATE).item()

            if speech_prob >= _SPEECH_THRESHOLD:
                if not pipeline.is_speaking:
                    pipeline.is_speaking = True
                    pipeline.speech_chunks = 0
                pipeline.silence_chunks = 0
                pipeline.speech_chunks += 1
                pipeline.speech_audio += chunk
            elif pipeline.is_speaking:
                pipeline.silence_chunks += 1
                pipeline.speech_audio += chunk  # include trailing silence for context

                if pipeline.silence_chunks >= _SILENCE_CHUNKS:
                    # End of speech detected
                    if pipeline.speech_chunks >= _MIN_SPEECH_CHUNKS:
                        self._queue.put((display_name, pipeline.speech_audio))
                    pipeline.reset_vad_state()

    def _get_pipeline(self, user_id: int) -> UserVoicePipeline:
        with self._pipeline_lock:
            if user_id not in self._pipelines:
                self._pipelines[user_id] = UserVoicePipeline()
            return self._pipelines[user_id]

    def _transcription_worker(self):
        """Dequeue completed utterances, transcribe with Whisper, forward text."""
        while not self._shutdown_event.is_set():
            try:
                display_name, audio_bytes = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            audio_float = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            with self._whisper_lock:
                segments, _ = self._whisper_model.transcribe(
                    audio_float,
                    language="en",
                    beam_size=5,
                    vad_filter=False,  # we already did VAD
                )
                text = " ".join(seg.text.strip() for seg in segments).strip()

            if text:
                self.process_text_fn(text, speaker=display_name)

    def cleanup(self):
        """Reset per-user pipelines (e.g. on /stop). Keeps model loaded."""
        with self._pipeline_lock:
            self._pipelines.clear()
        # Drain any pending transcription items
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def shutdown(self):
        """Full shutdown — stop worker thread."""
        self._shutdown_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        self.cleanup()
