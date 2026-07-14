---
name: Milestone 5 Model Framework v1
description: Architecture and key decisions for smartagent/models/ (ModelManager, ModelRegistry, BaseModel providers, PromptBuilder, ConversationContext, ResponseParser) — read before touching the Model Framework or wiring a real provider.
---

# Model Framework v1

## Layout
`smartagent/models/{base,providers,registry,manager,context,prompts,responses,config}/`,
deliberately mirroring the Tool Engine v1 structural pattern (registry +
engine/manager + loader + base class + context) since it was the closest
existing analog in the codebase.

## Key decisions

**Abstract future-provider stubs are excluded from discovery for free.**
`providers/future_providers.py` ships 12 design-only `BaseModel` subclasses
(Ollama, OpenAI, Anthropic, Gemini, LM Studio, OpenRouter, Azure OpenAI,
Bedrock, DeepSeek, Mistral, vLLM, llama.cpp). Each overrides only the 4
required identity properties and leaves the abstract action methods
(`generate`/`stream`/`load`/`embed`) unimplemented, so `inspect.isabstract()`
is `True` and they can't be instantiated. `model_loader.discover_provider_classes()`
filters on `not inspect.isabstract(candidate)`, so these stubs are
automatically skipped — no special-casing "future" vs "real" providers.
**Why:** satisfies "design-only, do not implement" without a second
discovery path or a naming convention that could be gamed by accident.
**How to apply:** when implementing a real provider later, just fill in
the abstract methods on the existing stub class (don't create a new file)
— the moment it's concrete, discovery picks it up with no other changes.

**No model auto-loads by default — preserves pre-Milestone-5 Brain behavior.**
`ModelManager.generate()`/`stream()` raise `NoActiveModelError` unless a
caller explicitly `load()`s/`switch()`es a model, or `ModelSettings.default_model_id`
(sourced from `Settings.default_model_id`, default `""`) names a registered
one. Out of the box this means `module_bindings.model_handler` still
returns `success=False` for arbitrary free text, exactly like the old
`ModelClient.generate()` raising `NotImplementedError` — zero observable
regression to `tests/test_agent.py`'s fallback-to-`unknown` behavior.
**Why:** Milestone 5 had to ship the framework without silently changing
what the Brain does for every existing message.
**How to apply:** set `Settings.default_model_id = "mock"` (or call
`agent.model_manager.switch("mock")`) to make the `model` handler actually
succeed via `MockModelProvider`.

**`generate()` returns raw provider-shaped output; `ResponseParser` normalizes it.**
`BaseModel.generate()` implementations return whatever dict shape is
natural for that provider (e.g. `MockModelProvider` returns
`{"content", "usage", ...}`). `ResponseParser.parse()` checks a small
ordered list of common key names per field (`content`/`text`/`output_text`/`message`
for the text field, etc.) rather than assuming one fixed shape.
**Why:** keeps providers simple and gives `ResponseParser` a real job
normalizing genuinely different vendor shapes once real providers land.
**How to apply:** a new provider's response dict does not need to match
`MockModelProvider`'s exactly — just use one of the recognized key names
per field, or extend `ResponseParser`'s key lists if a provider needs a
genuinely new key.

**Legacy `ModelClient`/`SkillContext.model` untouched.** Kept exactly as
Milestone 1 left it; `ModelManager` is additive (`agent.model_manager`
alongside `agent.model`), not a replacement. `SkillContext.model`'s type
was explicitly left as `ModelClient`, not touched.
**Why:** `tests/test_skills.py` constructs `SkillContext` directly with
`ModelClient(...)`; changing that field's type was out of Milestone 5's
scope and risked unrelated regressions.
**How to apply:** if Skills are ever migrated to use the Model Framework,
that's a separate, explicit milestone — don't fold it into unrelated work.

## Test count history
276 (Milestone 4 baseline) -> 369 after Milestone 5 (93 new tests in
`tests/test_models.py`), 0 regressions.
