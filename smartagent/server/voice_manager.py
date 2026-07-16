"""
MARK Voice Manager — fully local speech pipeline.

Pipeline
--------
Microphone → OpenWakeWord → Silero/Energy VAD → faster-whisper STT → MARK → Piper TTS → Speakers

Three modes
-----------
push_to_talk  Browser holds PTT button, records audio, POSTs to /voice/transcribe.
              VoiceManager transcribes and emits VoiceTranscribed.
continuous    Backend captures mic continuously; VAD detects speech; Whisper transcribes.
wake_word     Same as continuous but only activates after the configured wake phrase.

All processing is local. No cloud required.
"""
from __future__ import annotations

import asyncio
import io
import logging
import queue
import threading
import time
import wave
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------

class VoiceState:
    IDLE         = "idle"
    LISTENING    = "listening"       # recording / waiting for speech
    TRANSCRIBING = "transcribing"    # Whisper is running
    THINKING     = "thinking"        # MARK is processing the transcription
    SPEAKING     = "speaking"        # TTS is playing
    ERROR        = "error"


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------

@dataclass
class VoiceSettings:
    enabled:      bool  = False
    mode:         str   = "push_to_talk"   # push_to_talk | continuous | wake_word
    wake_phrase:  str   = "hey mark"
    whisper_model: str  = "base"           # tiny | base | small | medium | large-v3
    language:     str   = "en"
    tts_voice:    str   = "en_US-lessac-medium"   # piper voice name
    tts_speed:    float = 1.0
    sample_rate:  int   = 16000
    muted:        bool  = False
    auto_submit:  bool  = True             # auto-send transcription to MARK
    vad_threshold: float = 0.015           # energy VAD threshold
    silence_frames: int = 6               # consecutive silent chunks → end of utterance


# ---------------------------------------------------------------------------
# VoiceManager
# ---------------------------------------------------------------------------

class VoiceManager:
    """
    Manages the full local voice pipeline.

    Lifecycle
    ---------
    1. Call ``install(event_bus, connection_manager, loop)`` once at server start.
    2. Call ``start()`` to begin capturing / listening.
    3. Call ``stop()`` to halt the pipeline.
    4. For push-to-talk, call ``transcribe_bytes(pcm_bytes)`` directly.
    5. Call ``speak(text)`` to synthesise and play a response.
    """

    def __init__(self) -> None:
        self.settings = VoiceSettings()
        self._state   = VoiceState.IDLE
        self._running = False

        # Threading
        self._capture_thread: threading.Thread | None = None
        self._tts_thread:     threading.Thread | None = None

        # Event infrastructure (wired by install())
        self._event_bus:    Any | None = None
        self._conn_manager: Any | None = None
        self._loop:         asyncio.AbstractEventLoop | None = None

        # Lazy-loaded inference models
        self._whisper:   Any | None = None   # faster_whisper.WhisperModel
        self._oww:       Any | None = None   # openwakeword.Model

        # Audio queue fed by sounddevice callback → capture thread consumer
        self._audio_q: queue.Queue[Any] = queue.Queue(maxsize=200)

        # Lock for TTS so we don't overlap
        self._tts_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def install(
        self,
        event_bus: Any,
        connection_manager: Any,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Wire the manager to the live event bus and WebSocket manager."""
        self._event_bus    = event_bus
        self._conn_manager = connection_manager
        self._loop         = loop
        logger.info("VoiceManager installed")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self, name: str, **payload: Any) -> None:
        """Publish on the EventBus (thread-safe, silently ignores errors)."""
        if self._event_bus is not None:
            try:
                self._event_bus.publish(name, **payload)
            except Exception:
                pass

    def _broadcast_direct(self, msg: dict) -> None:
        """
        Bypass EventBus and broadcast a message directly over WebSocket.
        Used for voice events when the bus may not be active (between runs).
        """
        if self._conn_manager is None or self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._conn_manager.broadcast(msg),
                self._loop,
            )
        except RuntimeError:
            pass

    def _voice_event(self, name: str, **payload: Any) -> None:
        """Emit a voice event both via EventBus and directly over WS."""
        self._emit(name, **payload)
        self._broadcast_direct({
            "type":      "event",
            "name":      name,
            "payload":   payload,
            "timestamp": _now_iso(),
        })

    def _set_state(self, state: str) -> None:
        self._state = state
        self._voice_event("VoiceStateChanged", state=state)
        logger.debug("VoiceManager state → %s", state)

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> tuple[bool, str]:
        """
        Start the voice pipeline.

        Returns (success, error_message).
        """
        if self._running:
            return True, ""

        # Ensure Whisper is loadable before we commit to starting
        try:
            self._load_whisper()
        except Exception as exc:
            msg = f"Failed to load Whisper ({self.settings.whisper_model}): {exc}"
            logger.error("VoiceManager.start: %s", msg)
            self._voice_event("VoiceError", error=msg)
            return False, msg

        self._running = True

        if self.settings.mode in ("continuous", "wake_word"):
            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                daemon=True,
                name="mark-voice-capture",
            )
            self._capture_thread.start()

        self._set_state(VoiceState.LISTENING)
        self._voice_event("VoiceStarted", mode=self.settings.mode)
        return True, ""

    def stop(self) -> None:
        """Stop the voice pipeline gracefully."""
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=3)
            self._capture_thread = None
        self._set_state(VoiceState.IDLE)
        self._voice_event("VoiceStopped")

    # ------------------------------------------------------------------
    # Push-to-talk (called from API endpoint)
    # ------------------------------------------------------------------

    def transcribe_bytes(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """
        Transcribe raw 16-bit little-endian PCM mono audio.

        Called synchronously from ``/voice/transcribe`` inside
        ``asyncio.to_thread()`` so it doesn't block the event loop.
        """
        self._set_state(VoiceState.TRANSCRIBING)
        try:
            import numpy as np
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            return self._run_whisper(audio, sample_rate)
        finally:
            if self._running:
                self._set_state(VoiceState.LISTENING)
            else:
                self._set_state(VoiceState.IDLE)

    def transcribe_wav_bytes(self, wav_bytes: bytes) -> str:
        """
        Transcribe audio delivered as a WAV file (bytes).

        Used when the browser sends a Blob from MediaRecorder.
        """
        try:
            import numpy as np
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                rate    = wf.getframerate()
                frames  = wf.readframes(wf.getnframes())
                audio   = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            return self._run_whisper(audio, rate)
        except Exception as exc:
            logger.error("VoiceManager.transcribe_wav_bytes: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # TTS
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """
        Speak *text* via Piper TTS (non-blocking; runs in a daemon thread).

        If Piper is unavailable, emits ``VoiceTTSFallback`` so the frontend
        can use the browser's built-in SpeechSynthesis API instead.
        """
        if self.settings.muted or not text.strip():
            return

        t = threading.Thread(
            target=self._tts_worker,
            args=(text,),
            daemon=True,
            name="mark-voice-tts",
        )
        t.start()

    def _tts_worker(self, text: str) -> None:
        with self._tts_lock:
            self._set_state(VoiceState.SPEAKING)
            self._voice_event("VoiceSpeakingStarted", text=text)
            try:
                success = self._piper_speak(text)
                if not success:
                    # Signal browser fallback
                    self._voice_event("VoiceTTSFallback", text=text)
            except Exception as exc:
                logger.error("VoiceManager TTS error: %s", exc)
                self._voice_event("VoiceTTSFallback", text=text)
            finally:
                self._voice_event("VoiceSpeakingDone")
                self._set_state(
                    VoiceState.LISTENING if self._running else VoiceState.IDLE
                )

    def _piper_speak(self, text: str) -> bool:
        """
        Synthesise text with Piper and play it via sounddevice.

        Returns True on success, False if Piper is not installed.
        """
        import shutil, subprocess
        import numpy as np

        piper_bin = shutil.which("piper") or shutil.which("piper-tts")

        if piper_bin is None:
            # Try Python piper package
            try:
                from piper.voice import PiperVoice  # type: ignore
                voice = PiperVoice.load(self.settings.tts_voice)
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    voice.synthesize(text, wf)
                buf.seek(0)
                self._play_wav_bytes(buf.read())
                return True
            except ImportError:
                return False

        proc = subprocess.run(
            [
                piper_bin,
                "--model",       self.settings.tts_voice,
                "--length_scale", str(1.0 / max(self.settings.tts_speed, 0.1)),
                "--output_raw",
            ],
            input=text.encode(),
            capture_output=True,
        )
        if proc.returncode != 0:
            logger.warning("piper returned %d: %s", proc.returncode, proc.stderr[:200])
            return False

        try:
            import sounddevice as sd
            audio = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
            sd.play(audio, samplerate=22050)
            sd.wait()
            return True
        except Exception as exc:
            logger.warning("VoiceManager: sounddevice playback failed: %s", exc)
            return False

    def _play_wav_bytes(self, wav_bytes: bytes) -> None:
        import numpy as np, sounddevice as sd
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            rate   = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            audio  = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio, samplerate=rate)
        sd.wait()

    # ------------------------------------------------------------------
    # Continuous / wake-word capture loop (runs in background thread)
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        """Background thread: captures audio, detects wake word, runs VAD, transcribes."""
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError as exc:
            logger.error("VoiceManager: missing audio dependency: %s", exc)
            self._voice_event("VoiceError", error=f"sounddevice not installed: {exc}")
            self._set_state(VoiceState.ERROR)
            return

        if self.settings.mode == "wake_word":
            self._load_oww()

        sr          = self.settings.sample_rate
        chunk_dur   = 0.5        # seconds per chunk
        chunk_size  = int(sr * chunk_dur)
        speech_buf: list = []
        silence_count  = 0
        in_speech      = False
        wake_active    = (self.settings.mode != "wake_word")

        def _sd_callback(indata: Any, frames: int, _t: Any, status: Any) -> None:
            if status:
                logger.debug("sounddevice status: %s", status)
            self._audio_q.put_nowait(indata[:, 0].copy())

        try:
            with sd.InputStream(
                samplerate=sr,
                channels=1,
                dtype="float32",
                blocksize=chunk_size,
                callback=_sd_callback,
            ):
                while self._running:
                    try:
                        chunk = self._audio_q.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    # ── Wake word ────────────────────────────────────────
                    if not wake_active:
                        if self._oww is not None:
                            try:
                                import numpy as np
                                chunk_i16 = (chunk * 32768).astype("int16")
                                preds = self._oww.predict(chunk_i16)
                                score = max(preds.values(), default=0.0)
                                if score > 0.5:
                                    wake_active = True
                                    self._voice_event("VoiceWakeWordDetected", score=float(score))
                                    self._set_state(VoiceState.LISTENING)
                            except Exception as exc:
                                logger.debug("OWW prediction error: %s", exc)
                        continue

                    # ── VAD (energy-based) ────────────────────────────────
                    import numpy as np
                    energy    = float(np.sqrt(np.mean(chunk ** 2)))
                    is_speech = energy > self.settings.vad_threshold

                    if is_speech:
                        speech_buf.append(chunk)
                        in_speech     = True
                        silence_count = 0
                    elif in_speech:
                        speech_buf.append(chunk)
                        silence_count += 1
                        if silence_count >= self.settings.silence_frames:
                            # End of utterance
                            utterance     = np.concatenate(speech_buf)
                            speech_buf    = []
                            in_speech     = False
                            silence_count = 0
                            if len(utterance) > sr * 0.5:          # > 0.5 s
                                self._transcribe_utterance(utterance, sr)
                            if self.settings.mode == "wake_word":
                                wake_active = False
                                self._set_state(VoiceState.LISTENING)

        except Exception as exc:
            logger.error("VoiceManager capture loop failed: %s", exc)
            self._voice_event("VoiceError", error=str(exc))
            self._set_state(VoiceState.ERROR)

    def _transcribe_utterance(self, audio: Any, sample_rate: int) -> None:
        """Called from the capture thread after an utterance is detected."""
        self._set_state(VoiceState.TRANSCRIBING)
        try:
            text = self._run_whisper(audio, sample_rate)
            if text:
                self._voice_event("VoiceTranscribed", text=text)
                logger.info("VoiceManager transcribed: %r", text[:80])
        except Exception as exc:
            logger.error("VoiceManager transcription error: %s", exc)
            self._voice_event("VoiceError", error=f"Transcription failed: {exc}")
        finally:
            if self._running:
                self._set_state(VoiceState.LISTENING)
            else:
                self._set_state(VoiceState.IDLE)

    # ------------------------------------------------------------------
    # Model loading (lazy, called at most once each)
    # ------------------------------------------------------------------

    def _load_whisper(self) -> None:
        if self._whisper is not None:
            return
        from faster_whisper import WhisperModel  # type: ignore
        logger.info("VoiceManager: loading Whisper model '%s'…", self.settings.whisper_model)
        self._whisper = WhisperModel(
            self.settings.whisper_model,
            device="cpu",
            compute_type="int8",
        )
        logger.info("VoiceManager: Whisper ready")

    def _load_oww(self) -> None:
        if self._oww is not None:
            return
        try:
            from openwakeword.model import Model  # type: ignore
            # "alexa" bundled model acts as a generic wake-word demo;
            # users can swap for a custom ONNX model.
            self._oww = Model(wakeword_models=["alexa"], inference_framework="onnx")
            logger.info("VoiceManager: OpenWakeWord ready")
        except Exception as exc:
            logger.warning("VoiceManager: could not load OWW: %s", exc)

    def _run_whisper(self, audio: Any, sample_rate: int) -> str:
        """Run faster-whisper inference and return the transcript string."""
        self._load_whisper()
        import numpy as np
        # Resample to 16 kHz if needed
        if sample_rate != 16000:
            try:
                import resampy  # type: ignore
                audio = resampy.resample(audio, sample_rate, 16000)
            except ImportError:
                pass  # Whisper can handle other rates via its internal resampler

        segments, _info = self._whisper.transcribe(
            audio,
            language=self.settings.language or None,
            beam_size=5,
            vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status_dict(self) -> dict:
        return {
            "state":   self._state,
            "running": self._running,
            "settings": {
                "enabled":       self.settings.enabled,
                "mode":          self.settings.mode,
                "wake_phrase":   self.settings.wake_phrase,
                "whisper_model": self.settings.whisper_model,
                "language":      self.settings.language,
                "tts_voice":     self.settings.tts_voice,
                "tts_speed":     self.settings.tts_speed,
                "muted":         self.settings.muted,
                "auto_submit":   self.settings.auto_submit,
            },
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

voice_manager = VoiceManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
