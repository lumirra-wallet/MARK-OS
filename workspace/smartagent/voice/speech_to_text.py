"""
Speech-to-text interface.

Defines `SpeechToText`, the placeholder abstraction SmartAgent will use to
transcribe spoken audio into text. No real transcription backend (e.g. a
cloud STT API or a local model) is wired up yet.
"""

from __future__ import annotations


class SpeechToText:
    """Converts audio input into text for the core agent to process."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def transcribe(self, audio_data: bytes) -> str:
        """
        Transcribe raw audio bytes into text.

        Placeholder implementation: raises `NotImplementedError` since no
        speech recognition backend has been wired up yet.
        """
        # TODO: integrate a real speech-to-text backend (e.g. a hosted API
        # or local model) and return the transcribed text.
        raise NotImplementedError("Speech-to-text is not implemented yet.")
