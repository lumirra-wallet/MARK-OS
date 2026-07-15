"""
Text-to-speech interface.

Defines `TextToSpeech`, the placeholder abstraction SmartAgent will use to
speak its responses aloud. No real synthesis backend (e.g. a cloud TTS API
or a local model) is wired up yet.
"""

from __future__ import annotations


class TextToSpeech:
    """Converts text responses from the core agent into spoken audio."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def speak(self, text: str) -> None:
        """
        Synthesize and play speech audio for `text`.

        Placeholder implementation: raises `NotImplementedError` since no
        text-to-speech backend has been wired up yet.
        """
        # TODO: integrate a real text-to-speech backend and play/return
        # the resulting audio instead of raising.
        raise NotImplementedError("Text-to-speech is not implemented yet.")
