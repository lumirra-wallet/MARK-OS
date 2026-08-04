"""
Voice Providers Package.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from smartagent.config.settings import Settings
from smartagent.voice.providers.abstract_provider import VoiceProvider
from smartagent.voice.providers.gemini_live_provider import GeminiLiveProvider
from smartagent.voice.providers.openai_realtime_provider import OpenAIRealtimeProvider
from smartagent.voice.providers.azure_provider import AzureProvider

logger = logging.getLogger("smartagent.voice.providers")


def get_voice_provider(
    provider_name: Optional[str] = None,
    settings: Optional[Settings] = None,
    **kwargs: Any,
) -> VoiceProvider:
    """
    Factory function to instantiate the active VoiceProvider.
    """
    if settings is None:
        settings = Settings.load()

    provider = (provider_name or settings.voice_provider).lower()

    if provider in ("gemini_live", "gemini", "google"):
        logger.info("Selected Voice Provider: GeminiLiveProvider")
        return GeminiLiveProvider(
            api_key=kwargs.get("api_key") or settings.gemini_api_key,
            model=kwargs.get("model") or settings.gemini_live_model,
            voice_name=kwargs.get("voice_name") or settings.gemini_live_voice,
            tools=kwargs.get("tools"),
        )
    elif provider in ("openai_realtime", "openai"):
        logger.info("Selected Voice Provider: OpenAIRealtimeProvider")
        return OpenAIRealtimeProvider(
            api_key=kwargs.get("api_key"),
        )
    elif provider in ("azure", "azure_speech"):
        logger.info("Selected Voice Provider: AzureProvider")
        return AzureProvider(
            subscription_key=kwargs.get("subscription_key"),
        )
    else:
        raise ValueError(f"Unknown voice provider '{provider}'. Choose 'gemini_live', 'openai_realtime', or 'azure'.")
