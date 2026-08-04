"""
Asynchronous Streaming Microphone Input.

Captures 16kHz 16-bit mono PCM audio from local microphone using PyAudio or SoundDevice,
pushing chunks to an asyncio.Queue for low-latency streaming to the voice provider.
Falls back to non-blocking silent/simulated stream when no physical mic is available (e.g. headless Linux server).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("smartagent.voice.audio_input")

# Chunk size for 100ms at 16kHz 16-bit mono (16000 samples/sec * 2 bytes/sample * 0.1 sec = 3200 bytes)
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK_SIZE = 3200


class AudioInput:
    """
    Asynchronous microphone audio streamer.
    """

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        channels: int = 1,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels

        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stream = None
        self._pyaudio_instance = None

    async def start(self) -> None:
        """Start microphone capture loop."""
        if self._running:
            return

        self._running = True
        loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._capture_loop(loop))
        logger.info("Microphone audio capture started.")

    async def stop(self) -> None:
        """Stop microphone capture."""
        self._running = False
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

        logger.info("Microphone audio capture stopped.")

    async def get_audio_chunk(self) -> bytes:
        """Fetch next recorded PCM audio chunk (blocking async call)."""
        return await self._queue.get()

    async def _capture_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Background thread capture loop with automatic fallback."""
        try:
            import pyaudio

            self._pyaudio_instance = pyaudio.PyAudio()
            self._stream = self._pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size // 2,  # samples count
            )
            logger.info("PyAudio microphone stream opened successfully.")

            while self._running:
                # Non-blocking PyAudio read via thread executor
                data = await loop.run_in_executor(
                    None, self._stream.read, self.chunk_size // 2, False
                )
                if data:
                    if self._queue.full():
                        try:
                            self._queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    await self._queue.put(data)

        except ImportError:
            logger.warning("PyAudio not installed; trying sounddevice fallback...")
            await self._capture_loop_sounddevice(loop)
        except Exception as exc:
            logger.warning(f"Microphone init failed ({exc}); running synthetic audio standby loop...")
            await self._capture_loop_synthetic()

    async def _capture_loop_sounddevice(self, loop: asyncio.AbstractEventLoop) -> None:
        """Fallback capture using sounddevice."""
        try:
            import sounddevice as sd

            def callback(indata, frames, time_info, status):
                if status:
                    logger.debug(f"SoundDevice status: {status}")
                pcm = bytes(indata)
                loop.call_soon_threadsafe(
                    lambda: self._queue.put_nowait(pcm) if not self._queue.full() else None
                )

            with sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=self.chunk_size // 2,
                dtype="int16",
                channels=self.channels,
                callback=callback,
            ):
                while self._running:
                    await asyncio.sleep(0.1)

        except Exception as exc:
            logger.warning(f"Sounddevice capture failed ({exc}); falling back to synthetic loop.")
            await self._capture_loop_synthetic()

    async def _capture_loop_synthetic(self) -> None:
        """Synthetic silence loop for environments without physical mic hardware."""
        silent_chunk = b"\x00" * self.chunk_size
        interval = (self.chunk_size / 2) / self.sample_rate  # duration in seconds
        while self._running:
            await asyncio.sleep(interval)
            if not self._queue.full():
                await self._queue.put(silent_chunk)
