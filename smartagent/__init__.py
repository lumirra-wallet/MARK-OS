"""
SmartAgent
==========

A modular, extensible personal AI assistant.

This package is intentionally organized into small, focused subpackages so
that new capabilities (memory backends, tools, voice interfaces, scheduled
automations, etc.) can be added independently without entangling unrelated
concerns. Each subpackage currently contains placeholder implementations
that define the expected shape of the code to come.

Subpackages:
    brain       - The central orchestrator: decides which skills/tools to
                  use, consults memory, and produces responses.
    memory      - Short-term and long-term memory storage/retrieval.
    models      - Language model backend clients used by the brain to
                  generate responses.
    skills      - Higher-level, composed capabilities built from tools,
                  memory, and model calls (e.g. "set a reminder").
    tools       - Low-level, single-purpose capabilities the agent can
                  invoke (e.g. web search, calculators, file access).
    voice       - Speech-to-text and text-to-speech interfaces.
    vision      - Image/video understanding interfaces.
    automation  - Scheduled/background tasks and event-driven triggers.
    config      - Centralized configuration and settings management.
    ui          - User-facing front-ends (starting with a CLI) that drive
                  the brain.
    logs        - Centralized logging setup.
"""

__version__ = "0.1.0"
