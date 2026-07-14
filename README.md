# SmartAgent

SmartAgent is a personal AI assistant, built incrementally. This repository
currently contains a clean, modular project scaffold — placeholder
implementations only. Real functionality (language model reasoning,
persistent memory, skills, tools, voice, vision, and automations) will be
layered in one feature at a time, inside the package structure below.

## Project layout

```
smartagent/
├── main.py             # Process entry point — boots the agent and CLI
├── brain/              # The agent orchestrator (agent.py)
├── memory/             # Conversation/fact storage and retrieval
├── models/             # Language model backend clients
├── skills/             # Composed, user-facing capabilities
├── tools/              # Low-level, single-purpose capabilities
├── voice/              # Speech-to-text / text-to-speech interfaces
├── vision/             # Image/video understanding interfaces
├── automation/         # Scheduled/background tasks
├── config/             # Centralized settings
├── ui/                 # User-facing front-ends (CLI today)
├── logs/               # Centralized logging setup
├── research/           # Trusted-source research, summarized + owner-approved before storage
└── planning/           # Goal tracking and task decomposition
tests/                  # Test suite, mirrors the smartagent package structure
```

See `SMARTAGENT.md` for MARK's identity, mission, principles, and
long-term architecture vision — this repository is the implementation of
that vision, built incrementally.

## Running it

```bash
pip install -r requirements.txt
python -m smartagent.main
```

This currently prints a startup message and echoes messages back — there
is no real reasoning yet.

## Running tests

```bash
pytest
```

## Status

Scaffold only. Every module under `smartagent/` contains a documented,
working placeholder (not empty stubs) so the project is importable and
testable end-to-end. Features will be implemented module by module next.
