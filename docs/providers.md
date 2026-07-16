# MARK AI OS — LLM Providers

## Overview

MARK supports four LLM providers, selected via the `ACTIVE_PROVIDER` environment variable.
The system auto-detects the best available provider if `ACTIVE_PROVIDER` is not set.

## Auto-detection order

1. `ACTIVE_PROVIDER` env var (explicit)
2. `GITHUB_TOKEN` present → `github`
3. `OPENAI_API_KEY` present → `openai`
4. `ANTHROPIC_API_KEY` present → `anthropic`
5. Default → `ollama`

## Supported providers

### GitHub Models (`ACTIVE_PROVIDER=github`)

**Best for:** Replit deployments, Azure-hosted models, zero cost with GitHub token.

```bash
GITHUB_TOKEN=ghp_...
ACTIVE_PROVIDER=github  # optional if auto-detection is enabled
```

Available models (set at runtime via the Models panel or REST API):
- `gpt-4.1-mini` (default)
- `gpt-4.1` (coding)
- `gpt-4o-mini`
- `text-embedding-3-small` (embeddings)

### OpenAI (`ACTIVE_PROVIDER=openai`)

**Best for:** Production deployments with fine-grained model control.

```bash
OPENAI_API_KEY=sk-...
ACTIVE_PROVIDER=openai
OPENAI_DEFAULT_MODEL=gpt-4o-mini       # optional
```

Set `OPENAI_BASE_URL` to point at Azure OpenAI, Together AI, Groq, or any
OpenAI-compatible endpoint.

### Anthropic (`ACTIVE_PROVIDER=anthropic`)

**Best for:** Long context tasks, analysis, writing.

```bash
ANTHROPIC_API_KEY=sk-ant-...
ACTIVE_PROVIDER=anthropic
ANTHROPIC_DEFAULT_MODEL=claude-3-5-haiku-20241022  # optional
```

Note: Anthropic has no native embedding API. Set `OPENAI_API_KEY` to enable
embedding support (uses `text-embedding-3-small` as fallback).

### Ollama (`ACTIVE_PROVIDER=ollama`)

**Best for:** Fully local, private, offline development.

```bash
# Ollama must be running: https://ollama.ai
OLLAMA_HOST=http://localhost:11434     # default
OLLAMA_DEFAULT_MODEL=llama3.1:8b
OLLAMA_CODING_MODEL=qwen2.5-coder:7b
```

Pull models first: `ollama pull llama3.1:8b`

## Provider interface

Every provider implements:

```python
class MyProvider:
    def chat(self, messages: list[dict], **kwargs) -> dict:
        """Synchronous chat completion."""

    def stream_chat(self, messages: list[dict], **kwargs) -> Iterator[str]:
        """Token-by-token streaming."""

    def embed(self, text: str, **kwargs) -> list[float]:
        """Generate embeddings for a single text."""

    def embeddings(self, text: str, **kwargs) -> list[float]:
        """Alias for embed()."""

    def list_models(self) -> list[dict]:
        """Return available models."""

    def health(self) -> dict:
        """Return health status."""

    def switch_model(self, model_name: str) -> None:
        """Switch the active model."""
```

## Switching providers at runtime

Via REST API:

```bash
curl -X POST http://localhost:8000/providers/switch \
  -H "Content-Type: application/json" \
  -d '{"provider": "openai", "model": "gpt-4o"}'
```

Via the Models panel in the dashboard (Provider tab → Switch).

## Adding a new provider

1. Create `smartagent/llm/your_provider.py` implementing the interface above.
2. Add `"your_provider"` to `_VALID_PROVIDERS` in `smartagent/llm/factory.py`.
3. Add the auto-detect condition in `_auto_default_provider()`.
4. Wire it in `_wire_provider()`.
5. Add an entry to `_PROVIDERS` in `smartagent/server/api_providers.py`.

No other files need changing.
