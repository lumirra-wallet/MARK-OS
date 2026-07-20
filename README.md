# MARK AI Operating System

MARK is an AI operating system — a layered system of agents, engines, and tools that work together to plan, execute, debug, and ship software. It runs as an interactive console (REPL) and can drive multi-agent teams to build, test, debug, and ship software autonomously.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Console / REPL (UI)                               │
├─────────────────────────────────────────────────────────────────────┤
│  Software Engineer  │  DevLoop  │  Long Running Engine              │
├─────────────────────────────────────────────────────────────────────┤
│  CEO Agent  │  Team Planner  │  Team Runner                        │
├─────────────┼───────────────────────────────────────────────────────┤
│  Executive  │  Workers: Coding, Testing, Debug, Git, Research...  │
├─────────────┼───────────────────────────────────────────────────────┤
│  Debug Loop │  Quality Runner  │  File Editor v2                   │
├─────────────┼───────────────────────────────────────────────────────┤
│  Brain v2   │  Mind OS v1  │  Memory  │  Knowledge  │  Skills v1   │
├─────────────┼───────────────────────────────────────────────────────┤
│  Model Manager (Ollama)  │  Tool Engine v1  │  Skill Engine v1    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
# Start the interactive console (REPL)
python -m smartagent.main

# Inside the REPL:
mark> engineer Build a REST API with CRUD endpoints
mark> engineer --no-confirm Build a SaaS billing system
mark> long-run Build a SaaS product
mark> ceo Build a full-stack application with React and FastAPI
mark> dev-loop --commit Fix the authentication module
mark> validate           # Run Phase 9 validation suite (5 scenarios)
mark> validate           # Run Phase 9 validation suite
mark> help
```

---

## Architecture

MARK is built as a layered system:

| Layer | Components | Purpose |
|-------|------------|---------|
| **UI** | Console/REPL | Interactive command interface |
| **Agents** | Software Engineer, DevLoop, Long Running, CEO, Team Planner, Team Runner | High-level agents that orchestrate work |
| **Executive** | ExecutiveController | Central coordinator, routes to workers |
| **Workers** | Coding, Testing, Debug, Git, Research, File Ops, etc. | Single-purpose workers |
| **Execution** | Debug Loop, Quality Runner, File Editor v2 | Execution infrastructure |
| **Core Engines** | Brain v2, Mind OS v1, Memory, Knowledge, Skills v1 | Core cognitive engines |
| **Infrastructure** | Model Manager (Ollama), Tool Engine v1, Skill Engine v1 | Infrastructure engines |

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed architecture diagrams.

---

## Implemented Subsystems

| Subsystem | Status | Location | Description |
|-----------|--------|----------|-------------|
| **Memory** | ✅ Implemented | `smartagent/memory/` | Markdown vault, persistent memory |
| **Brain v2** | ✅ Implemented | `smartagent/brain/` | Router, IntentAnalyzer, DecisionEngine, ModuleRegistry |
| **Skills Engine v1** | ✅ Implemented | `smartagent/skills/` | 6 built-in skills, registry, sandbox |
| **Tool Engine v1** | ✅ Implemented | `smartagent/tools/` | 15 built-in tools, safety sandbox, registry |
| **Model Framework v1** | ✅ Implemented | `smartagent/models/` | ModelManager, MockModelProvider, 12 provider stubs |
| **Mind OS v1** | ✅ Implemented | `smartagent/mind/` | ExecutiveController + 9 engines |
| **Planning** | ✅ Implemented | `smartagent/planning/` | GoalManager, TaskQueueManager |
| **Research** | ✅ Implemented | `smartagent/research/` | ResearchManager, SourceValidator |
| **Voice** | 📋 Placeholder | `smartagent/voice/` | STT/TTS interfaces (stubs) |
| **Vision** | 📋 Placeholder | `smartagent/vision/` | Vision interfaces (stubs) |
| **Automation** | 📋 Placeholder | `smartagent/automation/` | Automation interfaces (stubs) |

### Mind OS v1 Engines (9 Engines)

| Engine | Module | Description |
|--------|--------|-------------|
| **ExecutiveController** | `smartagent/mind/` | Central coordinator, MindProviders DI |
| **SelfModel** | `mind/self_model/` | Self-model with diff tracking |
| **Identity** | `mind/identity/` | IdentityEngine, loads `SMARTAGENT.md` |
| **WorkingMemory** | `mind/working_memory/` | TTL-based short-term scratch space |
| **Attention** | `mind/attention/` | Importance ranking, bounded focus, interrupt/resume |
| **Context** | `mind/context/` | ContextManager, ContextBundle assembly |
| **Confidence** | `mind/confidence/` | Heuristic scoring from evidence/conflicts |
| **StateMachine** | `mind/state/` | 12 named internal states, bounded transitions |
| **Reflection** | `mind/reflection/` | Post-task self-assessment, memory-worthiness flags |
| **Homeostasis** | `mind/homeostasis/` | Health metrics, 10 digital signals, explicit `tick()` |

---

## Quick Start Commands

| Mode | Command | Use Case |
|------|---------|----------|
| **Default** | `mark> engineer <goal>` | Full pipeline with clarification |
| **Quick** | `mark> engineer --no-confirm <goal>` | Skip confirmations |
| **Long-running** | `mark> long-run <goal>` | Tasks >5 min, produces CompletionReport |
| **Debug loop** | `mark> dev-loop --commit <goal>` | Unattended fix→test→commit cycles |
| **Multi-agent** | `mark> ceo <goal>` | Complex projects needing team planning |
| **Validate** | `mark> validate` | Phase 9 validation gate (5 scenarios) |

### Session Management

```bash
# Inside REPL: type 'exit' or press Ctrl+D
mark> exit

# Clean shutdown saves:
#   • Project memory (current project state)
#   • Session history (command log)
#   • Worker states (in-progress checkpoints)
#   • Model connections (Ollama cleanup)
```

```bash
# Resume last session
python -m smartagent.main --resume

# List recent sessions
mark> session list

# Restore specific session
mark> session restore <session-id>
```

---

## Running Tests

```bash
# Full test suite (1900+ tests)
pytest

# By milestone/area
pytest tests/test_engineer.py         # M25 — Software Engineer
pytest tests/test_dev_loop.py         # M24 — Dev Loop
pytest tests/test_long_running.py     # M23 — Long Running
pytest tests/test_project_memory.py   # M22 — Project Memory
pytest tests/test_git.py              # M21 — Git Engine
pytest tests/test_quality_runner.py   # v2.0 — Quality Runner
pytest tests/test_dashboard.py        # v2.0 — Dashboard
pytest tests/test_file_editor_v2.py   # v2.0 — File Editor v2
pytest tests/test_brain_v2.py         # Brain v2
pytest tests/test_skills.py           # Skills Engine v1
pytest tests/test_tools.py            # Tool Engine v1
pytest tests/test_mind.py             # Mind OS v1
pytest tests/test_memory.py           # Memory
pytest tests/test_models.py           # Model Framework
pytest tests/test_planning.py         # Planning
pytest tests/test_research.py         # Research
```

---

## Project Structure

```
smartagent/
├── main.py                 # Process entry point — boots the agent and CLI
├── brain/                  # Brain v2: BrainRouter, IntentAnalyzer, DecisionEngine,
│                           # ModuleRegistry, ActionResult, EventBus, agent.py
├── memory/                 # Persistent Markdown memory vault
├── knowledge/              # Knowledge Engine v1: KnowledgeManager, KnowledgeGraph,
│                           # Concept/Relationship/Source/Evidence models,
│                           # ConfidenceEngine, KnowledgeInbox, OntologyEngine,
│                           # QueryEngine, KnowledgeSearch, KnowledgeStorage,
│                           # KnowledgeStats
├── models/                 # Model Framework v1: ModelManager, ModelRegistry,
│                           # BaseModel providers, PromptBuilder, ConversationContext,
│                           # ResponseParser, ModelSettings, MockModelProvider,
│                           # 12 provider stubs
├── mind/                   # MARK Mind OS v1: ExecutiveController, SelfModel,
│                           # IdentityEngine, WorkingMemory, AttentionManager,
│                           # ContextManager, ConfidenceEngine, StateMachine,
│                           # ReflectionEngine, Homeostasis
├── skills/                 # Composed, user-facing capabilities (6 built-in)
├── tools/                  # Low-level, single-purpose capabilities (15 built-in)
├── voice/                  # Speech-to-text / text-to-speech interfaces (stubs)
├── vision/                 # Image/video understanding interfaces (stubs)
├── automation/             # Scheduled/background tasks (stubs)
├── config/                 # Centralized settings
├── ui/                     # User-facing front-ends (CLI today)
├── logs/                   # Centralized logging setup
├── research/               # Trusted-source research, summarized + owner-approved
└── planning/               # Goal tracking and task decomposition
vault/                      # Persistent memories, one .md file per memory
knowledge/                  # Structured knowledge graph: JSON files per concept,
│                           # relationship, source, evidence item, inbox item
│                           # knowledge/ontology.json — hierarchical category tree
│                           # knowledge/stats_history.json — growth-over-time
tests/                      # Test suite, mirrors smartagent package structure
```

---

## Milestones

| Phase | Milestones | Description |
|-------|------------|-------------|
| **Foundation** | 1–10 | Brain, Mind, Memory, Knowledge, Models, Ollama, Streaming |
| **Intelligence** | 11–17 | Executive, Workers, CEO, Multi-Agent, Workspace |
| **Execution OS** | 18–21 | Scanner, FileEditor, DebugLoop, Git Engine |
| **Production** | 22–25 | Project Memory, Long Running, Dev Loop, Software Engineer |
| **v2.0** | — | Quality Runner, Dashboard, Reliability, Validation |

See [ROADMAP.md](ROADMAP.md) for detailed milestone status and what's next.

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture diagrams and component relationships |
| [ROADMAP.md](ROADMAP.md) | Milestone plan, current status, and what's next |
| [CLAUDE.md](CLAUDE.md) | Development guide for AI assistants working on this codebase |

---

## Requirements

- **Python** ≥ 3.11
- **Ollama** (for local LLM inference) — optional, MockModelProvider works offline
- **pytest** for running tests

```bash
pip install -r requirements.txt
```

---

## License

MIT