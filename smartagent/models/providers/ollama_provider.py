"""
OllamaProvider — Milestone 9 / Milestone 10 upgrade.

A concrete ``BaseModel`` implementation that talks to a locally-running
Ollama server (default ``http://127.0.0.1:11434``).

Architecture rule (unchanged from every prior milestone):

    Brain
      ↓
    ModelManager
      ↓
    BaseModel interface     ← THIS file sits here
      ↓
    OllamaProvider
      ↓
    Ollama Local API

Nothing above ``ModelManager`` ever imports this module.  The Brain,
Skills, and the Console commands communicate only through
``agent.model_manager`` — never through a provider instance directly.

Discovery:
    ``_exclude_from_discovery = True`` tells ``model_loader`` to skip
    auto-instantiation of this class.  ``ModelManager.load_ollama_models()``
    explicitly creates and registers the configured model instances so the
    correct ``base_url`` and ``model_name`` from ``Settings`` are used.

Fallback behaviour:
    If Ollama is unavailable, ``generate()`` returns a dict whose ``content``
    key is the message ``"Ollama server unavailable."``  It never raises.
    ``health()`` honestly reports ``healthy=False`` in that case.
    ``load()`` always sets ``_status = LOADED`` so model switching still works
    regardless of server availability — the health check is the right place
    to surface connectivity problems.

HTTP:
    Uses only ``urllib.request`` from the standard library — no third-party
    packages required.  All calls are synchronous with a configurable timeout.

Streaming (Milestone 9 / 10):
    ``generate_stream()`` and ``chat_stream()`` use ``stream: true`` on
    ``/api/chat`` and yield tokens as they arrive.  ``stream()`` delegates
    to ``generate_stream()`` for backward compatibility.

Warmup (Milestone 10):
    When ``warmup_enabled=True``, ``load()`` sends a tiny one-token
    generation so the model is immediately resident in memory.

Embeddings:
    ``embed()`` raises ``NotImplementedError`` per the architecture spec
    (embeddings are a separate future milestone).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from smartagent.logs.logger import get_logger
from smartagent.models.base.base_model import BaseModel, ModelHealth, ModelStatus

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Exclusion marker — prevents model_loader from auto-discovering this class.
# ModelManager.load_ollama_models() registers instances explicitly instead.
# ---------------------------------------------------------------------------
_EXCLUDE_FROM_DISCOVERY = True


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class OllamaModelInfo:
    """
    Metadata for a single model installed on the Ollama server.

    Equivalent to one entry from ``ollama list`` / ``GET /api/tags``.
    """

    name: str
    size: int            # bytes
    family: str
    modified_at: str     # ISO-8601
    status: str = "available"


# ---------------------------------------------------------------------------
# Discovery helper
# ---------------------------------------------------------------------------


class OllamaModelDiscovery:
    """
    Queries the Ollama server for its installed model list.

    Equivalent to running ``ollama list`` locally — reads ``GET /api/tags``.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self._base_url = base_url.rstrip("/")

    def list_models(self, timeout: float = 5.0) -> list[OllamaModelInfo]:
        """
        Return metadata for every model installed on the Ollama server.

        Returns an empty list (never raises) if Ollama is unreachable.
        """
        url = f"{self._base_url}/api/tags"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models") or []
            result: list[OllamaModelInfo] = []
            for entry in models:
                details = entry.get("details") or {}
                result.append(
                    OllamaModelInfo(
                        name=entry.get("name", ""),
                        size=int(entry.get("size", 0)),
                        family=str(details.get("family", "unknown")),
                        modified_at=str(entry.get("modified_at", "")),
                        status="available",
                    )
                )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("OllamaModelDiscovery: could not reach %s — %s", url, exc)
            return []

    def is_model_installed(self, model_name: str, timeout: float = 5.0) -> bool:
        """Return ``True`` if *model_name* appears in the installed list."""
        return any(m.name == model_name for m in self.list_models(timeout=timeout))


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class OllamaProvider(BaseModel):
    """
    Connects MARK to one specific Ollama model (e.g. ``llama3.1:8b``).

    One ``OllamaProvider`` instance per model name is registered with
    ``ModelManager``.  ``ModelManager.load_ollama_models()`` creates them.

    Args:
        model_name:      The Ollama model tag (e.g. ``"llama3.1:8b"``).
        base_url:        Base URL of the local Ollama server.
        timeout:         HTTP timeout in seconds for generate/stream calls.
        warmup_enabled:  Send a tiny generation on ``load()`` to keep the
                         model resident in memory (Milestone 10).
    """

    # Tells model_loader to skip auto-discovery of this class.
    _exclude_from_discovery: bool = True

    def __init__(
        self,
        model_name: str = "llama3.1:8b",
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
        warmup_enabled: bool = False,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._warmup_enabled = warmup_enabled
        self._status = ModelStatus.UNLOADED
        self._call_count = 0

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        """Model id equals the Ollama tag so switching is intuitive."""
        return self._model_name

    @property
    def name(self) -> str:
        return f"Ollama/{self._model_name}"

    @property
    def provider(self) -> str:
        return "ollama"

    @property
    def version(self) -> str:
        return "1.0.0"

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    @property
    def context_window(self) -> int:
        return 128_000   # conservative; actual window depends on the model

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tools(self) -> bool:
        return False   # tool-call mapping is a future milestone

    @property
    def supports_images(self) -> bool:
        return False   # vision is a future milestone

    @property
    def supports_embeddings(self) -> bool:
        return False

    @property
    def supports_functions(self) -> bool:
        return False

    @property
    def call_count(self) -> int:
        """Number of ``generate()`` / ``chat()`` calls since the instance was created."""
        return self._call_count

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """No-op initialisation — Ollama manages model weights itself."""
        logger.info("OllamaProvider initialized: model=%s url=%s", self._model_name, self._base_url)

    def load(self) -> None:
        """
        Mark this model as loaded.

        Pings the Ollama server and logs whether the model is actually
        available — but always sets ``_status = LOADED`` so console commands
        like ``model use <name>`` work regardless of whether Ollama is running
        right now.  The real availability signal is ``health()``.

        When ``warmup_enabled`` is ``True``, sends a tiny one-token generation
        immediately so the model is resident in GPU/CPU memory and the first
        real response starts without the weight-loading delay (Milestone 10).
        """
        self._status = ModelStatus.LOADED
        try:
            disc = OllamaModelDiscovery(self._base_url)
            installed = [m.name for m in disc.list_models(timeout=5.0)]
            if self._model_name in installed:
                logger.info("OllamaProvider: %s confirmed installed on server", self._model_name)
            else:
                logger.warning(
                    "OllamaProvider: %s not found in server model list %s; "
                    "run 'ollama pull %s' to download it.",
                    self._model_name,
                    installed,
                    self._model_name,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OllamaProvider: could not reach Ollama at %s — %s", self._base_url, exc)

        if self._warmup_enabled:
            self._warmup()

    def unload(self) -> None:
        """Alias for ``shutdown()`` (symmetry with ``load()``)."""
        self.shutdown()

    def shutdown(self) -> None:
        """Release the model — no real resources to free on the Ollama side."""
        self._status = ModelStatus.UNLOADED
        logger.info("OllamaProvider: %s unloaded", self._model_name)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> ModelHealth:
        """
        Probe Ollama to confirm the server is reachable and the model is installed.

        Overrides the ``BaseModel`` default so ``ModelManager.health_check()``
        reports real connectivity rather than just checking ``_status``.

        Makes a direct HTTP call (rather than using ``OllamaModelDiscovery``
        which swallows exceptions) so it can distinguish:
          - server unreachable  → healthy=False, message contains "unreachable"
          - server up, model missing → healthy=False, message contains "not installed"
          - server up, model found  → healthy=True
        """
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        url = f"{self._base_url}/api/tags"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models") or []
            names = [m.get("name", "") for m in models]
            if self._model_name in names:
                return ModelHealth(
                    healthy=True,
                    status=self._status,
                    message=f"Ollama server reachable; {self._model_name} is installed.",
                    checked_at=now,
                )
            return ModelHealth(
                healthy=False,
                status=self._status,
                message=(
                    f"Ollama server reachable but {self._model_name!r} is not installed. "
                    f"Run: ollama pull {self._model_name}"
                ),
                checked_at=now,
            )
        except Exception as exc:  # noqa: BLE001
            return ModelHealth(
                healthy=False,
                status=ModelStatus.ERROR,
                message=f"Ollama server unreachable at {self._base_url}: {exc}",
                checked_at=now,
            )

    # ------------------------------------------------------------------
    # model_info
    # ------------------------------------------------------------------

    def model_info(self, timeout: float = 5.0) -> OllamaModelInfo | None:
        """
        Return metadata for this model from the Ollama server, or ``None``
        if the server is unreachable or the model is not installed.
        """
        disc = OllamaModelDiscovery(self._base_url)
        for m in disc.list_models(timeout=timeout):
            if m.name == self._model_name:
                return m
        return None

    # ------------------------------------------------------------------
    # Generation (non-streaming)
    # ------------------------------------------------------------------

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """
        Generate a response for *prompt* via ``POST /api/chat``.

        Returns a provider-shaped dict that ``ResponseParser`` normalises
        into a ``ParsedResponse``.  Never raises — Ollama failures surface
        as ``{"content": "Ollama server unavailable.", ...}``.

        Keyword args forwarded to Ollama: ``temperature``, ``top_p``,
        ``top_k``, ``max_tokens`` (mapped to ``num_predict``).
        """
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"OllamaProvider {self._model_name!r} must be load()ed before generate() is called."
            )
        self._call_count += 1

        messages = self._prompt_to_messages(prompt)
        options = self._build_options(kwargs)
        payload = {
            "model": self._model_name,
            "messages": messages,
            "stream": False,
            "options": options,
        }

        try:
            data = self._post("/api/chat", payload)
            message_content = (data.get("message") or {}).get("content", "")
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)
            return {
                "content": message_content,
                "tool_calls": [],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
                "finish_reason": "stop",
                "model": self._model_name,
            }
        except _OllamaUnavailable:
            logger.warning("OllamaProvider.generate: server unavailable for model %s", self._model_name)
            return {
                "content": "Ollama server unavailable.",
                "tool_calls": [],
                "usage": {},
                "finish_reason": "error",
                "model": self._model_name,
            }

    def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Low-level chat interface: send a list of ``{"role", "content"}`` dicts
        directly to ``POST /api/chat``.

        Returns the same provider-shaped dict as ``generate()``.
        """
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"OllamaProvider {self._model_name!r} must be load()ed before chat() is called."
            )
        self._call_count += 1

        options = self._build_options(kwargs)
        payload = {
            "model": self._model_name,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        try:
            data = self._post("/api/chat", payload)
            message_content = (data.get("message") or {}).get("content", "")
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)
            return {
                "content": message_content,
                "tool_calls": [],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
                "finish_reason": "stop",
                "model": self._model_name,
            }
        except _OllamaUnavailable:
            logger.warning("OllamaProvider.chat: server unavailable for model %s", self._model_name)
            return {
                "content": "Ollama server unavailable.",
                "tool_calls": [],
                "usage": {},
                "finish_reason": "error",
                "model": self._model_name,
            }

    # ------------------------------------------------------------------
    # Streaming (Milestone 9 / 10)
    # ------------------------------------------------------------------

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """
        Stream tokens from Ollama.

        Delegates to ``generate_stream()`` — kept for backward compatibility
        with any caller that already uses ``model.stream(prompt)``.
        """
        yield from self.generate_stream(prompt, **kwargs)

    def generate_stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """
        Stream tokens for *prompt* via ``POST /api/chat`` with ``stream: true``.

        Converts the flat prompt to a chat-style message list then delegates
        to ``_stream_messages()``.

        Raises:
            RuntimeError: If called before ``load()``.
        """
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"OllamaProvider {self._model_name!r} must be load()ed before generate_stream() is called."
            )
        self._call_count += 1
        messages = self._prompt_to_messages(prompt)
        yield from self._stream_messages(messages, **kwargs)

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[str]:
        """
        Stream tokens for a chat *messages* list via ``POST /api/chat`` with
        ``stream: true``.

        This is the native streaming path for providers that receive a
        pre-built message list (e.g. from ``ModelManager.chat_stream()``).

        Raises:
            RuntimeError: If called before ``load()``.
        """
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"OllamaProvider {self._model_name!r} must be load()ed before chat_stream() is called."
            )
        self._call_count += 1
        yield from self._stream_messages(messages, **kwargs)

    def _stream_messages(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[str]:
        """
        Core streaming implementation shared by ``generate_stream()`` and
        ``chat_stream()``.

        Sends *messages* to ``POST /api/chat`` with ``stream: true`` and
        yields each token as it arrives via newline-delimited JSON.
        Falls back to a single "unavailable" chunk if the server is unreachable.
        """
        options = self._build_options(kwargs)
        payload = {
            "model": self._model_name,
            "messages": messages,
            "stream": True,
            "options": options,
        }
        url = f"{self._base_url}/api/chat"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = (chunk.get("message") or {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        break
        except Exception:  # noqa: BLE001
            yield "Ollama server unavailable."

    # ------------------------------------------------------------------
    # Warmup (Milestone 10)
    # ------------------------------------------------------------------

    def _warmup(self) -> None:
        """
        Send a tiny one-token generation to keep the model resident in memory.

        This prevents the weight-loading delay on the first real user request.
        Called by ``load()`` when ``warmup_enabled=True``.  Silently skipped
        if the server is unreachable.
        """
        try:
            payload = {
                "model": self._model_name,
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
                "options": {"num_predict": 1},
            }
            self._post("/api/chat", payload)
            logger.info("OllamaProvider: warmup complete for %s", self._model_name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("OllamaProvider: warmup skipped for %s (%s)", self._model_name, exc)

    def embed(self, text: str) -> list[float]:
        """Not implemented — embeddings are a future milestone."""
        raise NotImplementedError(
            "Embeddings are out of scope for Milestone 9 — "
            "no provider implements embed() yet."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST *payload* to *endpoint* and return the parsed JSON response."""
        url = f"{self._base_url}{endpoint}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise _OllamaUnavailable(str(exc)) from exc
        except OSError as exc:
            raise _OllamaUnavailable(str(exc)) from exc

    @staticmethod
    def _prompt_to_messages(prompt: str) -> list[dict[str, str]]:
        """
        Convert a flat prompt string into a ``messages`` list.

        Ollama's ``/api/chat`` expects chat-style messages.  A flat prompt
        is wrapped as a single ``user`` message; prompts that already
        contain ``System:`` / ``User:`` section headers are split correctly.
        """
        # Simple heuristic: if the prompt has a "System:" section, parse it.
        if prompt.startswith("System:"):
            messages: list[dict[str, str]] = []
            lines = prompt.splitlines()
            current_role = ""
            current_lines: list[str] = []
            for line in lines:
                if line.startswith("System:"):
                    if current_role and current_lines:
                        messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
                    current_role = "system"
                    current_lines = [line[len("System:"):].strip()]
                elif line.startswith("User:"):
                    if current_role and current_lines:
                        messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
                    current_role = "user"
                    current_lines = [line[len("User:"):].strip()]
                elif line.startswith("assistant:"):
                    if current_role and current_lines:
                        messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
                    current_role = "assistant"
                    current_lines = [line[len("assistant:"):].strip()]
                else:
                    current_lines.append(line)
            if current_role and current_lines:
                messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
            return messages if messages else [{"role": "user", "content": prompt}]
        return [{"role": "user", "content": prompt}]

    @staticmethod
    def _build_options(kwargs: dict[str, Any]) -> dict[str, Any]:
        """Map ModelSettings generation kwargs to Ollama option names."""
        options: dict[str, Any] = {}
        if "temperature" in kwargs:
            options["temperature"] = float(kwargs["temperature"])
        if "top_p" in kwargs:
            options["top_p"] = float(kwargs["top_p"])
        if "top_k" in kwargs:
            options["top_k"] = int(kwargs["top_k"])
        if "max_tokens" in kwargs:
            options["num_predict"] = int(kwargs["max_tokens"])
        return options


class _OllamaUnavailable(Exception):
    """Internal signal: Ollama server not reachable; used only within this module."""
