"""
Image analysis interface.

Defines `ImageAnalyzer`, the placeholder abstraction SmartAgent will use to
interpret image input (e.g. describing a photo, reading text in a
screenshot). No real vision backend is wired up yet.
"""

from __future__ import annotations


class ImageAnalyzer:
    """Analyzes image input and produces a textual description for the core agent."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def describe(self, image_data: bytes) -> str:
        """
        Produce a textual description of `image_data`.

        Placeholder implementation: raises `NotImplementedError` since no
        vision backend has been wired up yet.
        """
        # TODO: integrate a real vision backend (e.g. a hosted API or
        # local model) and return a description of the image.
        raise NotImplementedError("Image analysis is not implemented yet.")
