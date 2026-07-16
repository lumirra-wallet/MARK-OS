"""
smartagent.llm — Provider-agnostic LLM abstraction layer.

Every AI feature — chat, agents, RAG, memory, voice, planning, coding,
and evaluation — should call the active provider through this package.
Never import OpenAI, Ollama, or any vendor SDK directly from feature code.

Quick start::

    from smartagent.llm.factory import get_provider_factory
    factory = get_provider_factory()
    provider = factory.get_provider()        # respects ACTIVE_PROVIDER env var
    response = provider.chat([{"role": "user", "content": "Hello"}])

Switching providers requires only changing ACTIVE_PROVIDER (or calling the
REST API at POST /providers/switch).  No feature code needs to change.
"""

from smartagent.llm.base import LLMProvider  # noqa: F401
