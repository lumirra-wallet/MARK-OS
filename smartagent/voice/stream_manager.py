"""
Real-Time Voice Stream Manager.

Orchestrates full-duplex audio I/O, Voice Activity Detection, VoiceProvider (Gemini Live),
and the Elina OS Brain into a seamless, continuous, real-time voice experience.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from smartagent.brain.elina_bridge import ElinaBridge
from smartagent.config.settings import Settings
from smartagent.voice.audio_input import AudioInput
from smartagent.voice.audio_output import AudioOutput
from smartagent.voice.conversation import (
    ConversationSession,
    InterruptionManager,
    TurnManager,
    TurnState,
)
from smartagent.voice.providers import get_voice_provider
from smartagent.voice.providers.abstract_provider import (
    AudioOutputEvent,
    ErrorEvent,
    InterruptionEvent,
    TextOutputEvent,
    ToolCallEvent,
    TurnCompleteEvent,
    VoiceProvider,
)
from smartagent.voice.vad import VoiceActivityDetector

logger = logging.getLogger("smartagent.voice.stream_manager")


class RealtimeStreamManager:
    """
    Core orchestrator for Elina's Gemini Live real-time voice assistant.
    """

    def __init__(
        self,
        elina: Optional[ElinaBridge] = None,
        provider: Optional[VoiceProvider] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or Settings.load()
        self.elina = elina or ElinaBridge()

        self.audio_input = AudioInput(
            sample_rate=self.settings.audio_sample_rate_in,
            channels=self.settings.audio_channels,
        )
        self.audio_output = AudioOutput(
            sample_rate=self.settings.audio_sample_rate_out,
            channels=self.settings.audio_channels,
        )
        self.vad = VoiceActivityDetector(threshold=self.settings.vad_threshold)

        # Initialize Voice Provider (Gemini Live)
        self.provider = provider or get_voice_provider(
            provider_name=self.settings.voice_provider,
            settings=self.settings,
            tools=self.elina.get_tool_declarations(),
        )

        self.turn_manager = TurnManager()
        self.interruption_manager = InterruptionManager(audio_output=self.audio_output)
        self.session = ConversationSession()

        self._running = False
        self._input_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start real-time voice assistant pipeline."""
        if self._running:
            return

        logger.info("Initializing Elina Real-Time Voice Assistant...")

        # Connect audio input/output
        await self.audio_input.start()
        await self.audio_output.start()

        # Connect Gemini Live API
        await self._connect_provider_with_retry()

        self._running = True

        # Start concurrent asyncio workers
        self._input_task = asyncio.create_task(self._microphone_loop())
        self._receive_task = asyncio.create_task(self._provider_event_loop())

        logger.info("⚡ Elina Live Voice Assistant is active and listening!")

    async def _connect_provider_with_retry(self, max_retries: int = 5) -> None:
        """Connect to voice provider with exponential backoff retry."""
        attempt = 0
        backoff = 1.0
        while attempt < max_retries:
            try:
                await self.provider.connect()
                return
            except Exception as exc:
                attempt += 1
                logger.warning(
                    f"Connection attempt {attempt}/{max_retries} failed: {exc}. Retrying in {backoff:.1f}s..."
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 15.0)

        err = f"Could not connect to Gemini Live API after {max_retries} attempts."
        logger.error(err)
        raise RuntimeError(err)

    async def stop(self) -> None:
        """Stop all streams and disconnect provider."""
        self._running = False

        if self._input_task:
            self._input_task.cancel()
            self._input_task = None

        if self._receive_task:
            self._receive_task.cancel()
            self._receive_task = None

        await self.audio_input.stop()
        await self.audio_output.stop()
        await self.provider.disconnect()

        logger.info(self.session.get_summary())
        logger.info("Elina Live Voice Assistant stopped.")

    async def _microphone_loop(self) -> None:
        """Continuously stream microphone audio chunks to Gemini Live while performing VAD."""
        logger.info("Started microphone streaming worker.")
        while self._running:
            try:
                pcm_chunk = await self.audio_input.get_audio_chunk()

                # VAD & Barge-in check
                is_speaking = self.vad.is_speech(pcm_chunk)
                if is_speaking:
                    # If assistant is currently speaking or executing, trigger instant barge-in!
                    if self.audio_output.is_playing or self.turn_manager.state in (
                        TurnState.ASSISTANT_SPEAKING,
                        TurnState.ASSISTANT_THINKING,
                    ):
                        logger.info("⚡ [VAD] User speech detected during assistant output! Triggering barge-in.")
                        self.interruption_manager.trigger_interruption()
                        self.turn_manager.transition_to(TurnState.USER_SPEAKING)

                # Send raw audio PCM chunk to Gemini Live API
                await self.provider.send_audio_chunk(pcm_chunk)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in microphone loop: {exc}", exc_info=True)
                await asyncio.sleep(0.05)

    async def _provider_event_loop(self) -> None:
        """Process incoming events (audio chunks, transcripts, tool calls) from Gemini Live."""
        logger.info("Started provider event worker.")
        first_chunk_time: Optional[float] = None

        try:
            async for event in self.provider.receive_events():
                if not self._running:
                    break

                # 1. Handle Audio Output Chunks from Gemini
                if isinstance(event, AudioOutputEvent):
                    if first_chunk_time is None:
                        first_chunk_time = time.time()
                        if self.session.current_turn:
                            latency = (first_chunk_time - self.session.current_turn.timestamp) * 1000.0
                            self.session.current_turn.latency_ms = latency

                    self.turn_manager.transition_to(TurnState.ASSISTANT_SPEAKING)
                    self.audio_output.play_chunk(event.data)

                # 2. Handle Text Transcript Chunks
                elif isinstance(event, TextOutputEvent):
                    self.session.add_assistant_transcript(event.text)
                    print(event.text, end="", flush=True)

                # 3. Handle Interruption (Server Barge-in)
                elif isinstance(event, InterruptionEvent):
                    logger.info("⚡ Server recognized user interruption.")
                    self.interruption_manager.trigger_interruption()
                    self.turn_manager.transition_to(TurnState.USER_SPEAKING)

                # 4. Handle Tool Calls (Elina function execution)
                elif isinstance(event, ToolCallEvent):
                    self.turn_manager.transition_to(TurnState.EXECUTING_TOOL)
                    self.session.record_tool_call(event.name)

                    # Execute tool safely inside Elina
                    logger.info(f"Executing tool '{event.name}' via Elina bridge...")
                    result = await asyncio.to_thread(
                        self.elina.execute_tool, event.name, event.args
                    )

                    # Send result back to Gemini Live
                    await self.provider.send_tool_response(
                        call_id=event.call_id,
                        name=event.name,
                        response={"result": result},
                    )
                    self.turn_manager.transition_to(TurnState.ASSISTANT_THINKING)

                # 5. Handle Turn Completion
                elif isinstance(event, TurnCompleteEvent):
                    print()  # Newline after completed text output
                    self.session.finalize_turn()
                    first_chunk_time = None
                    self.turn_manager.transition_to(TurnState.IDLE)

                # 6. Handle Error / Disconnects
                elif isinstance(event, ErrorEvent):
                    logger.error(f"Provider Error: {event.message}")
                    if self.settings.auto_reconnect and self._running:
                        logger.info("Attempting automatic reconnection...")
                        await asyncio.sleep(1.0)
                        await self._connect_provider_with_retry()

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"Error in provider event loop: {exc}", exc_info=True)
