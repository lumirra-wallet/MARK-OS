"""
Language model client interface.

Defines `ModelClient`, the placeholder abstraction `SmartAgent` uses to
generate responses. No real backend (a hosted LLM API, a local model,
etc.) is wired up yet — this establishes the contract the rest of the
codebase depends on.
"""

from __future__ import annotations


class ModelClient:
    """
    Generates text responses from a configured language model backend.

    Args:
        model_name: Identifier for which model/backend to use. Placeholder
            only — no backend is actually selected or called yet.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate(self, prompt: str) -> str:
        """
        Generate a response for `prompt`.

        Placeholder implementation: raises `NotImplementedError` since no
        model backend has been wired up yet.
        """
        # TODO: call out to the configured model backend (self.model_name)
        # and return its generated text.
        raise NotImplementedError("Language model generation is not implemented yet.")
