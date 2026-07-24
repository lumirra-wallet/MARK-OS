"""
MARK's real spoken voice — a local Kokoro-82M engine (kokoro-onnx,
onnxruntime-based), never the browser's speechSynthesis.

Why kokoro-onnx and not the official `kokoro` PyPI package: the official
package requires Python <3.13 (verified against PyPI metadata), and this
server runs on Python 3.13. kokoro-onnx is the actively-used ONNX-runtime
community port with no such version ceiling, drops the PyTorch dependency,
and pairs with espeakng-loader to bundle its own espeak-ng library —
sidestepping the Windows DLL-locating bug that otherwise plagues Kokoro on
Windows (verified: espeakng_loader.get_library_path()/get_data_path()
resolve to real files bundled inside the pip package itself, no system
install needed).

One consistent voice for the whole process — MARK_VOICE below — not chosen
per request. af_bella was picked because it's the highest community-graded
English voice in Kokoro's set (see hexgrad/Kokoro-82M/VOICES.md); swap the
constant if a different identity is ever wanted, but it should stay one
fixed value, never vary per reply.

Model weights (kokoro-v1.0.onnx, voices-v1.0.bin — ~300MB combined) are
downloaded once from the kokoro-onnx GitHub release into a local cache
directory the first time this module is used; see _ensure_model_files().
"""

from __future__ import annotations

import logging
import os
import threading
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

MARK_VOICE = "af_bella"
SPEED = 1.0
LANG = "en-us"

_MODEL_RELEASE_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
# fp32 model. int8 was originally chosen for the smaller download, but
# benchmarked 3.5x SLOWER than fp32 on this CPU (12.3 s vs 3.5 s for the
# same 2.2 s sentence — quantized int8 ops fall off the fast path on this
# machine's instruction set). fp32 is the difference between MARK's voice
# lagging ~6x behind realtime and roughly keeping up. The bigger one-time
# download (~326 MB vs ~92 MB) is irrelevant next to that.
_MODEL_FILENAME = os.environ.get("MARK_TTS_MODEL_FILE", "kokoro-v1.0.onnx")
_CACHE_DIR = Path(os.environ.get("MARK_TTS_CACHE", str(Path.home() / ".cache" / "mark-tts")))
_MODEL_PATH = _CACHE_DIR / _MODEL_FILENAME
_VOICES_PATH = _CACHE_DIR / "voices-v1.0.bin"

_engine: Any = None
_engine_lock = threading.Lock()
_unavailable_reason: str | None = None


def _ensure_model_files() -> None:
    """Download the real model weights once, on first use — not shipped in
    the repo (too large), not faked with silence."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in ((_MODEL_FILENAME, _MODEL_PATH), ("voices-v1.0.bin", _VOICES_PATH)):
        if path.exists() and path.stat().st_size > 0:
            continue
        url = f"{_MODEL_RELEASE_BASE}/{name}"
        logger.info("tts_engine: downloading %s (first run only)...", name)
        tmp = path.with_name(path.name + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(path)
        logger.info("tts_engine: %s ready (%d bytes)", name, path.stat().st_size)


def _get_engine() -> Any:
    """Lazily construct and cache the real Kokoro engine. Raises on
    failure — callers decide the fallback (see is_available())."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        import espeakng_loader
        import onnxruntime as rt
        from kokoro_onnx import EspeakConfig, Kokoro

        _ensure_model_files()

        # Build the InferenceSession ourselves instead of letting Kokoro's
        # constructor do it: onnxruntime's default intra-op thread pool
        # SPIN-WAITS for work — measured on this machine as six native
        # threads each burning ~30% of a core (≈1.8 cores, "CPU at 100%")
        # CONTINUOUSLY after the first synthesis, even while MARK is
        # completely silent.  Disabling spinning parks the pool between
        # syntheses; a bounded thread count keeps one synthesis from
        # saturating every core while Whisper/VAD run beside it.
        sess_options = rt.SessionOptions()
        sess_options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        sess_options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        # Full core count: benchmarked identical to cpu//2 when idle, and
        # synthesis is bursty — with spinning off the threads park between
        # sentences, so there's no idle cost to the larger pool.
        sess_options.intra_op_num_threads = os.cpu_count() or 4
        session = rt.InferenceSession(
            str(_MODEL_PATH), sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )
        _engine = Kokoro.from_session(
            session, str(_VOICES_PATH),
            espeak_config=EspeakConfig(
                lib_path=espeakng_loader.get_library_path(),
                data_path=espeakng_loader.get_data_path(),
            ),
        )
        logger.info(
            "tts_engine: Kokoro engine ready, voice=%s (spin-wait disabled, %d threads)",
            MARK_VOICE, sess_options.intra_op_num_threads,
        )
        return _engine


def is_available() -> bool:
    """True once the real engine has initialized (downloading/loading real
    weights if this is the first call). Checked once at server startup so
    the frontend can be told upfront whether to expect real audio or fall
    back to the browser's emergency-only speechSynthesis — see api.py's
    SpeechEngineUnavailable event."""
    global _unavailable_reason
    try:
        _get_engine()
        return True
    except Exception as exc:
        _unavailable_reason = str(exc)
        logger.warning("tts_engine: real TTS engine unavailable: %s", exc)
        return False


def unavailable_reason() -> str | None:
    return _unavailable_reason


# Kokoro's native output rate — the frontend's audio player (markStore.ts)
# hardcodes this same value, since it can't discover it dynamically over
# the wire (PCM16 frames carry no header). If a future model file ever
# changes it, synthesize() below logs a loud warning rather than silently
# feeding the frontend audio at the wrong rate.
SAMPLE_RATE = 24000


def synthesize(text: str) -> bytes:
    """Synthesize *text* with MARK's one consistent voice; returns raw
    PCM16 mono bytes at SAMPLE_RATE. Real inference, blocking — call this
    from a worker thread, never the asyncio event loop. Returns b"" for
    empty/whitespace-only text."""
    text = text.strip()
    if not text:
        return b""
    engine = _get_engine()
    samples, sample_rate = engine.create(text, voice=MARK_VOICE, speed=SPEED, lang=LANG)
    if sample_rate != SAMPLE_RATE:
        logger.warning(
            "tts_engine: engine reported sample_rate=%d, expected %d — "
            "frontend playback will be pitched/timed wrong until this is reconciled",
            sample_rate, SAMPLE_RATE,
        )
    samples = np.asarray(samples, dtype=np.float32)
    clipped = np.clip(samples, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    return pcm16.tobytes()
