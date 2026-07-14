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
    core        - The central agent "brain": orchestrates requests, decides
                  which tools/memory to use, and produces responses.
    memory      - Short-term and long-term memory storage/retrieval.
    tools       - Pluggable capabilities the agent can invoke (e.g. web
                  search, calculators, file access) via a common interface.
    voice       - Speech-to-text and text-to-speech interfaces.
    config      - Centralized configuration and settings management.
    automation  - Scheduled/background tasks and event-driven triggers.
"""

__version__ = "0.1.0"
