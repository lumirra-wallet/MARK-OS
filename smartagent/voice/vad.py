"""
Voice Activity Detection (VAD) Engine.

Analyzes 16kHz PCM audio frames to detect user speech energy for barge-in (interruption)
and natural turn taking. Uses RMS energy calculation with optional WebRTC VAD augmentation.
"""

from __future__ import annotations

import logging
import math
import struct
from typing import Optional

from smartagent.config.settings import Settings

logger = logging.getLogger("smartagent.voice.vad")


class VoiceActivityDetector:
    """
    Voice Activity Detector for detecting human speech in raw PCM audio frames.
    """

    def __init__(
        self,
        threshold: Optional[float] = None,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
    ) -> None:
        settings = Settings.load()
        self.threshold = threshold if threshold is not None else settings.vad_threshold
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms

        self._webrtc_vad = None
        self._init_webrtc_vad()

    def _init_webrtc_vad(self) -> None:
        """Initialize WebRTC VAD if available."""
        try:
            import webrtcvad

            self._webrtc_vad = webrtcvad.Vad(mode=2)  # 0 to 3 (most aggressive)
            logger.info("WebRTC VAD initialized successfully.")
        except ImportError:
            logger.debug("webrtcvad not installed; using RMS energy VAD.")

    def calculate_rms(self, pcm_data: bytes) -> float:
        """Calculate Root Mean Square (RMS) energy normalized between 0.0 and 1.0."""
        if not pcm_data:
            return 0.0

        count = len(pcm_data) // 2
        if count == 0:
            return 0.0

        shorts = struct.unpack(f"<{count}h", pcm_data[: count * 2])
        sum_squares = sum(s * s for s in shorts)
        mean_square = sum_squares / count
        rms = math.sqrt(mean_square)

        # Normalize 16-bit max amplitude 32768
        return rms / 32768.0

    def is_speech(self, pcm_data: bytes) -> bool:
        """
        Check if the PCM audio chunk contains speech.
        Returns True if speech is detected above threshold.
        """
        if not pcm_data:
            return False

        rms_energy = self.calculate_rms(pcm_data)
        energy_speech = rms_energy > self.threshold

        # If webrtcvad is available, combine both energy and webrtcvad
        if self._webrtc_vad is not None:
            try:
                # WebRTC VAD requires exact frame lengths (10ms, 20ms, 30ms)
                bytes_per_frame = int(self.sample_rate * (self.frame_duration_ms / 1000.0) * 2)
                if len(pcm_data) >= bytes_per_frame:
                    frame = pcm_data[:bytes_per_frame]
                    webrtc_speech = self._webrtc_vad.is_speech(frame, self.sample_rate)
                    return energy_speech or webrtc_speech
            except Exception:
                pass

        return energy_speech
