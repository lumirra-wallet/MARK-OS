"""
Interruption (Barge-in) Controller.

Coordinates immediate stopping of assistant audio output when user speech is detected
during active playback.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from smartagent.voice.audio_output import AudioOutput

logger = logging.getLogger("smartagent.voice.conversation.interruptions")


class InterruptionManager:
    """
    Manages user barge-in and audio interruption callbacks.
    """

    def __init__(self, audio_output: Optional[AudioOutput] = None) -> None:
        self.audio_output = audio_output
        self._callbacks: List[Callable[[], None]] = []

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback function to execute on interruption."""
        self._callbacks.append(callback)

    def trigger_interruption(self) -> None:
        """
        Execute barge-in interruption.
        1. Clears speaker audio playback buffer immediately.
        2. Notifies registered listener callbacks.
        """
        logger.info("⚡ [InterruptionManager] Barge-in triggered! Halting speaker output.")
        if self.audio_output:
            self.audio_output.clear()

        for cb in self._callbacks:
            try:
                cb()
            except Exception as exc:
                logger.error(f"Error in interruption callback: {exc}")
