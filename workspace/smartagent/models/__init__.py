"""
Model Framework v1 — Milestone 5.

Decouples the Brain from any specific AI provider behind a single
`ModelManager` interface. Sub-packages:

    base/       BaseModel — the abstract contract every provider implements.
    providers/  Concrete providers (MockModelProvider) and design-only
                future-provider stubs (Ollama, OpenAI, Anthropic, ...).
    registry/   ModelRegistry + provider auto-discovery.
    manager/    ModelManager — the only component that talks to providers.
    context/    ConversationContext — history/summaries/goals/memory refs.
    prompts/    PromptBuilder — assembles provider-agnostic Prompt objects.
    responses/  ResponseParser — normalizes raw provider output.
    config/     ModelSettings — generation/timeout/future-credentials config.

`model_client.py` (the Milestone 1 placeholder `ModelClient`) is kept
as-is for backward compatibility — `SkillContext.model` and existing
tests still construct it directly. New code, and the Brain's `model`
module handler, use `ModelManager` instead (see
`smartagent.brain.module_bindings`).
"""
