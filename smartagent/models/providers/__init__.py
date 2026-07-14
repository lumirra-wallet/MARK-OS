"""
Model providers — concrete `BaseModel` implementations.

`mock_provider.py` holds `MockModelProvider`, the one provider Milestone 5
actually wires up: deterministic, no real AI, safe for tests/CI.

`future_providers.py` holds *design-only* interface stubs for providers
Milestone 5 explicitly does not implement (Ollama, OpenAI, Anthropic,
Gemini, LM Studio, OpenRouter, Azure, Bedrock, DeepSeek, Mistral, vLLM,
Llama.cpp) — see that module's docstring for why they stay abstract on
purpose.

`smartagent.models.registry.model_loader.discover_provider_classes()`
auto-discovers every *concrete* `BaseModel` subclass in this package, so
the future stubs (which stay abstract) are never accidentally registered.
"""
