"""
Asynchronous Streaming Speaker Output.

Plays incoming 24kHz 16-bit PCM audio chunks from Gemini Live / voice provider in real-time.
Supports immediate queue clearing and interruption (barge-in) when the user speaks while Elina is talking.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("smartagent.voice.audio_output")

DEFAULT_OUTPUT_SAMPLE_RATE = 24000


class AudioOutput:
    """
    Asynchronous speaker audio playback player.
    """

    def __init__(
        self,
        sample_rate: int = DEFAULT_OUTPUT_SAMPLE_RATE,
        channels: int = 1,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels

        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stream = None
        self._pyaudio_instance = None
        self._is_playing = False

    @property
    def is_playing(self) -> bool:
        return self._is_playing or not self._queue.empty()

    async def start(self) -> None:
        """Start speaker playback worker."""
        if self._running:
            return

        self._running = True
        loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._playback_loop(loop))
        logger.info("Speaker audio player started.")

    async def stop(self) -> None:
        """Stop player and release device."""
        self._running = False
        self.clear()

        if self._task:
            self._task.cancel()
            self._task = None

        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._pyaudio_instance:
            try:
                self._pyaudio_instance.terminate()
            except Exception:
                pass
            self._pyaudio_instance = None

        logger.info("Speaker audio player stopped.")

    def play_chunk(self, pcm_data: bytes) -> None:
        """Add PCM audio chunk to playback queue."""
        if not self._running or not pcm_data:
            return
        self._queue.put_nowait(pcm_data)

    def clear((self) -> None:
        """
        Immediately clear all queued audio chunks (Barge-in / Interruption).
        Flushes buffer immediately with zero delay.
        """
        cleared_count = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                cleared_count += 1
            except (asyncio.QueueEmpty, ValueError):
                break
        self._is_playing = False
        if cleared_count > 0:
            logger.info(f"⚡ [Barge-in] Flushed {cleared_count} pending audio chunks from playback queue.")

    async def _playback_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Playback loop feeding audio device."""
        try:
            import pyaudio

            self._pyaudio_instance = pyaudio.PyAudio()
            self._stream = self._pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
            )
            logger.info("PyAudio speaker stream opened.")

            while self._running:
                chunk = await self._queue.get()
                self._is_playing = True
                try:
                    await loop.run_in_executor(None, self._stream.write, chunk)
                except Exception as exc:
                    logger.error(f"Error writing audio chunk to speaker: {exc}")
                finally:
                    self._queue.task_done()
                    if self._queue.empty():
                        self._is_playing = False

        except ImportError:
            logger.warning("PyAudio not available for speaker; attempting sounddevice...")
            await self._playback_loop_sounddevice(loop)
        except Exception as exc:
            logger.warning(f"Speaker stream init failed ({exc}); running virtual playback loop.")
            await self._playback_loop_virtual()

    async def _playback_loop_sounddevice(self, loop: asyncio.AbstractEventLoop) -> None:
        """Fallback speaker playback using sounddevice."""
        try:
            import sounddevice as sd

            while self._running:
                chunk = await self._queue.get()
                self._is_playing = True
                try:
                    # Convert raw int16 PCM bytes to numpy array
                    import numpy as np
                    audio_array = np.frombuffer(chunk, dtype=np.int16)
                    await loop.run_in_executor(
                        None, sd.play, audio_array, self.sample_rate
                    )
                except Exception as exc:
                    logger.error(f"Sounddevice playback error: {exc}")
                finally:
                    self._queue.task_done()
                    if self._queue.empty():
                        self._is_playing = False

        except Exception as exc:
            logger.warning(f"Sounddevice playback failed ({exc}); falling back to virtual playback.")
            await self._playback_loop_virtual()

    async def _playback_loop_virtual(self) -> None:
        """Virtual playback drain loop for headless servers without sound cards."""
        while self._running:
            chunk = await self._queue.get()
            self._is_playing = True
            # Estimate playback duration
            duration = (len(chunk) / 2) / self.sample_rate
            await asyncio.sleep(duration * 0.1)  # fast drain in virtual mode
            self._queue.task_done()
            if self._queue.empty():
                self._is_playing = False
