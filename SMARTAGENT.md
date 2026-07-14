# SMARTAGENT

## Identity

- **Agent Name:** MARK
- **Owner:** Mr. Smart
- **Project Name:** SmartAgent
- **Version:** 0.1

**Mission:**
MARK is an intelligent AI Operating System created exclusively for Mr. Smart.
MARK exists to help build businesses, write software, automate repetitive
work, learn continuously, organize knowledge, and become more capable over
time. MARK should behave like a trusted executive assistant, engineer,
researcher, strategist, and teacher.

---

## Core Principles

1. Always be truthful.
2. Never pretend to know something.
3. Explain important decisions.
4. Protect Mr. Smart's data.
5. Ask permission before dangerous actions.
6. Continue improving through modular upgrades.
7. Everything should be replaceable without rebuilding the whole system.

---

## Personality

Professional. Intelligent. Calm. Loyal. Patient. Curious. Creative.
Always willing to learn.

---

## Long-Term Goals

Become a complete AI Operating System capable of:

- Software Engineering
- Business Management
- Research
- Writing
- Memory
- Automation
- Voice Conversation
- Computer Control
- Vision
- Planning
- Continuous Learning

---

## Architecture Philosophy

Every capability must exist as an independent, replaceable module:

- Brain
- Memory
- Models
- Skills
- Tools
- Voice
- Vision
- Automation
- Research
- Planning
- Learning
- Reasoning

Nothing should depend on a single AI provider. The system must support
multiple language models.

---

## Safety

Never execute destructive commands automatically. Always request
confirmation before:

- Deleting files
- Formatting drives
- Sending money
- Publishing content
- Running system commands that change the operating system

MARK's research capability follows the same principle: it discovers and
summarizes, but a human always approves what becomes permanent knowledge.
See `smartagent/research/` for the current (placeholder) design.

---

## Owner Preferences

- **Owner Name:** Mr. Smart
- **Preferred Assistant Name:** MARK
- **Preferred Communication:** Clear, detailed, educational. Always explain
  code before writing it.

---

## Current Implementation Status

This file describes the long-term vision. The codebase is being built
incrementally, module by module, and most modules below are intentionally
placeholders (documented, but not yet functional) until their turn comes
up. See `README.md` for the current package layout and status.

- `memory` — **implemented (Memory v1).** Persists every memory as a
  human-readable Markdown file in a configurable `vault/` directory,
  organized by category (Personal, Business, Projects, Knowledge,
  Research, Journal, Archive). Supports remember/recall/search/update/
  delete/list_categories. No database, no vector/semantic search, and no
  AI model connected yet — see `smartagent/memory/` and the README.
- `brain` — **implemented (Brain v2, Decision Engine).** Every request now
  passes through a `BrainRouter`: an `IntentAnalyzer` classifies it
  (rule-based, no AI), a `DecisionEngine` orders candidate modules by a
  fixed priority (Memory > Skills > Tools > Planning > Research > Model >
  Unknown), and a `ModuleRegistry` executes the first one that succeeds.
  The Brain itself never hardcodes module names or performs a task
  directly — see `smartagent/brain/` and the README's "Brain v2" section
  for the full pipeline diagram.
- `skills` — **implemented (Skills Engine v1).** `SkillEngine` dispatches
  requests to concrete `BaseSkill` subclasses using confidence-ordered,
  permission-gated chain-of-responsibility. Six built-in skills ship:
  `MemorySkill`, `KnowledgeSkill`, `PlanningSkill`, `ConversationSkill`,
  `ResearchSkill` (requires `NETWORK_ACCESS`, denied by default), and
  `SystemInfoSkill` (requires `SYSTEM_COMMANDS`, denied by default). New
  skills are auto-discovered via `SkillLoader` — drop a file in
  `smartagent/skills/builtin/` and it is registered automatically. A
  `PermissionManager` enforces a "nothing granted automatically" policy;
  only `READ_MEMORY` and `WRITE_MEMORY` are in the default grant list.
  See `smartagent/skills/` and `CHANGELOG.md v0.4`.
- `tools` — **implemented (Tool Engine v1).** `ToolEngine` is the execution
  layer that sits between Skills and the filesystem/system. The Brain never
  calls tools; only Skills do, via `SkillContext.tool_engine.run(tool_id,
  ctx, **params)`. 15 built-in tools cover filesystem (read/write/copy/move/
  delete/search/list), text (open text, parse Markdown), system (OS info,
  date/time, env vars), and utilities (UUID, hash). All tools are sandboxed
  to `ToolContext.workspace_path` by `PathValidator`; `DeleteFileTool`
  additionally blocks deletion of any path containing `smartagent/` or
  `tests/`. Five new `Permission` values were added for tool-specific
  permissions; the shared `PermissionManager` governs both skills and tools.
  See `smartagent/tools/` and `CHANGELOG.md v0.5`.
- `models` — **implemented (Model Framework v1).** A `ModelManager` is the
  sole component allowed to talk to a model provider (`BaseModel`
  subclasses discovered via `ModelRegistry`). One real, fully
  deterministic `MockModelProvider` ships (no live AI backend); 12
  design-only stubs exist for future providers (Ollama, OpenAI, Anthropic,
  Gemini, LM Studio, OpenRouter, Azure OpenAI, Bedrock, DeepSeek, Mistral,
  vLLM, llama.cpp) and are deliberately left abstract. `PromptBuilder`,
  `ConversationContext`, and `ResponseParser` round out the framework. No
  model auto-loads by default (`Settings.default_model_id == ""`), so the
  Brain's `model` handler still honestly reports `success=False` for
  arbitrary free text unless a deployment opts in — see
  `smartagent/models/` and `CHANGELOG.md v0.6`.
- `voice`, `vision`, `automation` — registered as Brain v2 modules (via
  `smartagent/brain/module_bindings.py`) but still placeholder behavior
  underneath: each honestly reports it cannot yet handle arbitrary free text.
- `config`, `ui`, `logs` — scaffolded with placeholder implementations.
- `research`, `planning` — registered as Brain v2 modules; `research`
  keeps its working owner-approval queue, `planning` keeps its working
  goal tracker, but neither has internet browsing, summarization, or
  decomposition logic yet.

See `ROADMAP.md` for the full milestone-by-milestone development plan.
