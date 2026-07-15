"""
Future provider interfaces — Milestone 5, Part 10. **Design-only. Do not implement.**

Milestone 5's explicit rules forbid connecting to any real cloud or local
model backend yet. This module exists purely to document, in code, the
shape each future provider's integration is expected to take once that
work is scheduled — without wiring up a single HTTP call, API key, or
subprocess.

Mechanism: each class below subclasses `BaseModel` and overrides only the
four *identity* properties (`id`, `name`, `provider`, `version`). None of
them override the required action methods (`initialize`, `load`,
`generate`, `stream`, `embed`, `shutdown`), so — per Python's `ABC` rules —
every class here remains abstract and **cannot be instantiated**:

    >>> OllamaModel()
    TypeError: Can't instantiate abstract class OllamaModel with abstract
    methods embed, generate, initialize, load, shutdown, stream

This also means `model_loader.discover_provider_classes()` (which skips
`inspect.isabstract()` classes, exactly like `discover_tool_classes()`
does) never registers these by accident — turning them into real
providers later requires a deliberate, separate change: implement the six
methods, give the class a real `__init__`, and only then will discovery
pick it up.
"""

from __future__ import annotations

from smartagent.models.base.base_model import BaseModel


class OllamaModel(BaseModel):
    """
    Future: local models served by Ollama (http://localhost:11434 by default).

    Would need: base URL from `ModelSettings` (never hardcoded), a
    `requests`/`httpx` call to `/api/generate` or `/api/chat`, streaming via
    Ollama's newline-delimited JSON, and a `load()` that verifies the model
    has been `ollama pull`-ed rather than pulling it automatically (pulling
    multi-GB weights as a side effect of `load()` would be surprising).
    """

    @property
    def id(self) -> str:
        return "ollama"

    @property
    def name(self) -> str:
        return "Ollama (local)"

    @property
    def provider(self) -> str:
        return "ollama"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class OpenAIModel(BaseModel):
    """
    Future: OpenAI's hosted Chat Completions / Responses API.

    Would need an API key sourced from an environment variable/secret via
    `ModelSettings` (never a hardcoded string), request/response mapping
    for `generate()`/`stream()` (SSE for streaming), and `supports_tools`/
    `supports_functions` wired to `True` once function-calling is mapped.
    """

    @property
    def id(self) -> str:
        return "openai"

    @property
    def name(self) -> str:
        return "OpenAI"

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class AnthropicModel(BaseModel):
    """Future: Anthropic's Messages API (Claude models). API key via `ModelSettings`, never hardcoded."""

    @property
    def id(self) -> str:
        return "anthropic"

    @property
    def name(self) -> str:
        return "Anthropic Claude"

    @property
    def provider(self) -> str:
        return "anthropic"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class GeminiModel(BaseModel):
    """Future: Google's Gemini API. API key via `ModelSettings`; would likely support `supports_images=True`."""

    @property
    def id(self) -> str:
        return "gemini"

    @property
    def name(self) -> str:
        return "Google Gemini"

    @property
    def provider(self) -> str:
        return "gemini"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class LMStudioModel(BaseModel):
    """Future: LM Studio's local OpenAI-compatible server (default http://localhost:1234/v1)."""

    @property
    def id(self) -> str:
        return "lmstudio"

    @property
    def name(self) -> str:
        return "LM Studio (local)"

    @property
    def provider(self) -> str:
        return "lmstudio"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class OpenRouterModel(BaseModel):
    """Future: OpenRouter's unified multi-provider API. API key via `ModelSettings`; model id is provider-namespaced."""

    @property
    def id(self) -> str:
        return "openrouter"

    @property
    def name(self) -> str:
        return "OpenRouter"

    @property
    def provider(self) -> str:
        return "openrouter"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class AzureOpenAIModel(BaseModel):
    """Future: Azure OpenAI Service. Needs endpoint + deployment name + API key/AD token via `ModelSettings`."""

    @property
    def id(self) -> str:
        return "azure_openai"

    @property
    def name(self) -> str:
        return "Azure OpenAI"

    @property
    def provider(self) -> str:
        return "azure"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class BedrockModel(BaseModel):
    """Future: AWS Bedrock. Needs AWS credentials/region via `ModelSettings`, not boto3 defaults baked into code."""

    @property
    def id(self) -> str:
        return "bedrock"

    @property
    def name(self) -> str:
        return "AWS Bedrock"

    @property
    def provider(self) -> str:
        return "bedrock"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class DeepSeekModel(BaseModel):
    """Future: DeepSeek's hosted API (OpenAI-compatible surface). API key via `ModelSettings`."""

    @property
    def id(self) -> str:
        return "deepseek"

    @property
    def name(self) -> str:
        return "DeepSeek"

    @property
    def provider(self) -> str:
        return "deepseek"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class MistralModel(BaseModel):
    """Future: Mistral's hosted API. API key via `ModelSettings`."""

    @property
    def id(self) -> str:
        return "mistral"

    @property
    def name(self) -> str:
        return "Mistral"

    @property
    def provider(self) -> str:
        return "mistral"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class VLLMModel(BaseModel):
    """Future: a self-hosted vLLM OpenAI-compatible inference server. Base URL via `ModelSettings`."""

    @property
    def id(self) -> str:
        return "vllm"

    @property
    def name(self) -> str:
        return "vLLM (self-hosted)"

    @property
    def provider(self) -> str:
        return "vllm"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"


class LlamaCppModel(BaseModel):
    """Future: `llama.cpp`'s server mode (or in-process bindings) for local GGUF models."""

    @property
    def id(self) -> str:
        return "llama_cpp"

    @property
    def name(self) -> str:
        return "llama.cpp (local)"

    @property
    def provider(self) -> str:
        return "llama_cpp"

    @property
    def version(self) -> str:
        return "0.0.0-design-only"
