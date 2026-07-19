# ARCHITECTURE.md

# MARK AIOS
## Complete System Architecture
### Version 1.0

This document defines the technical architecture of MARK AIOS.

It is the single source of truth for how every subsystem interacts.

Every engineer working on MARK must understand this document before implementing new functionality.

---

# ARCHITECTURE PHILOSOPHY

MARK is not a collection of AI APIs.

MARK is not a collection of workers.

MARK is not a frontend.

MARK is a living operating system.

Everything inside MARK exists to support one permanent intelligence.

Every subsystem exists to help MARK think, remember, communicate, and execute work.

Nothing should bypass MARK.

---

# HIGH LEVEL ARCHITECTURE

                    USER
                      │
        Voice │ Text │ Dashboard
                      │
             Interface Layer
                      │
              Intent Router
                      │
                 MARK Core
                      │
        ┌─────────────┼─────────────┐
        │             │             │
   Memory Manager  Mission Manager  Knowledge Manager
        │             │             │
        └─────────────┼─────────────┘
                      │
                Runtime Engine
                      │
        ┌─────────────┼─────────────┐
        │             │             │
 Worker Manager  Provider Manager  Event Bus
        │             │             │
        └─────────────┼─────────────┘
                      │
      Ollama | Claude | GPT | Gemini | Groq | Others

MARK sits at the center.

Everything communicates through MARK.

---

# DIRECTORY STRUCTURE

mark-aios/

core/
runtime/
workers/
memory/
knowledge/
missions/
voice/
providers/
plugins/
dashboard/
api/
config/
logs/
scripts/
docs/
tests/

Each directory has one responsibility.

Responsibilities should never overlap.

---

# CORE

Purpose:

The permanent intelligence.

Responsibilities:

Intent Analysis

Decision Making

Planning

Memory Access

Knowledge Access

Mission Control

Worker Coordination

Provider Selection

Personality

Conversation

MARK Core never directly calls providers.

It delegates through the Runtime.

---

# RUNTIME

Purpose:

The nervous system.

Responsibilities:

Connect every subsystem.

Manage lifecycle.

Route events.

Coordinate execution.

Maintain system health.

Runtime owns communication.

Nothing bypasses Runtime.

---

# EVENT BUS

Every subsystem communicates through events.

Examples:

Mission Started

Mission Finished

Memory Updated

Knowledge Learned

Worker Finished

Voice Started

Voice Stopped

Provider Changed

Dashboard Connected

Ollama Restarted

This prevents tight coupling.

---

# CONFIGURATION MANAGER

Owns:

Environment Variables

Configuration Files

Feature Flags

Provider Settings

Runtime Settings

No component should read .env directly.

Everything comes through Configuration Manager.

---

# PROVIDER MANAGER

Purpose:

Abstract every AI provider.

Supported providers:

Ollama

Claude

OpenRouter

Gemini

Groq

GitHub Models

Future providers

Workers never know which provider is active.

Only MARK decides.

---

# OLLAMA MANAGER

Responsibilities:

Detect installation

Start automatically

Restart automatically

Monitor health

Verify models

Expose runtime status

Never crash MARK if unavailable.

---

# MEMORY MANAGER

Contains:

Conversation Memory

Project Memory

User Memory

Mission Memory

Session Memory

Memory is persistent.

Memory belongs to MARK.

---

# KNOWLEDGE MANAGER

Purpose:

Convert memory into reusable understanding.

Example:

Memory:

"The user prefers voice."

Knowledge:

"Voice should become default interaction."

Knowledge grows.

Memory stores history.

---

# INTENT ROUTER

Every request begins here.

Intent Router classifies:

Conversation

Mission

Question

Automation

Research

Coding

System Control

Settings

Voice

Memory Request

Only after classification does MARK choose what happens next.

---

# CONVERSATION MODE

This is the default mode.

Pipeline:

User

↓

Intent Router

↓

MARK Core

↓

Memory

↓

Provider

↓

Response

Workers remain asleep.

Mission Manager remains inactive.

Minimal API usage.

Fast responses.

---

# MISSION MODE

Mission Pipeline:

User

↓

Intent Router

↓

Mission Manager

↓

Planning

↓

Worker Assignment

↓

Execution

↓

Review

↓

Memory Update

↓

Knowledge Update

↓

Mission Complete

Mission Mode activates engineering.

Conversation Mode does not.

---

# WORKER MANAGER

Workers never communicate directly.

Every worker communicates only through MARK.

Workers include:

Coding

Testing

Security

Documentation

Database

Deployment

Research

Analysis

Future workers

Workers execute.

MARK decides.

---

# VOICE RUNTIME

Pipeline:

Microphone

↓

Voice Activity Detection

↓

Speech Recognition

↓

Intent Router

↓

MARK Core

↓

Response

↓

Text To Speech

↓

Speaker

Voice should feel natural.

The user should not need to press Send.

---

# DASHBOARD

The dashboard represents the operating system.

It displays:

MARK Status

Mission Status

Workers

Voice

Memory

Knowledge

Provider

CPU

RAM

Logs

Health

Current Thinking

Chat is a secondary component.

The dashboard is primary.

---

# HEALTH MONITOR

Continuously monitors:

Runtime

Workers

Voice

Memory

Knowledge

Providers

CPU

RAM

Disk

Network

Ollama

If failures occur:

Recover automatically.

Notify if necessary.

Never stop MARK unnecessarily.

---

# PLUGIN SYSTEM

Plugins extend MARK.

Not modify MARK.

Examples:

Docker Plugin

Git Plugin

Email Plugin

Calendar Plugin

WhatsApp Plugin

Browser Plugin

Database Plugin

IoT Plugin

Every plugin communicates through Runtime.

---

# API MANAGER

Responsibilities:

Rate limiting

Retry logic

Authentication

Provider abstraction

Usage tracking

Cost tracking

Logging

No component should call APIs directly.

---

# LOGGING

Every subsystem logs:

Startup

Shutdown

Errors

Warnings

Provider changes

Mission lifecycle

Voice events

Worker execution

Logs should help future debugging.

---

# SECURITY

Secrets remain outside source code.

Everything sensitive belongs in:

.env

Encrypted storage

OS keychain (future)

Never hardcode credentials.

---

# GIT WORKFLOW

Main Branch

↓

Feature Branch

↓

Testing

↓

Review

↓

Merge

Every commit must explain:

Why

What changed

Architecture impact

Future AI engineers should understand history by reading Git.

---

# AUTOMATIC RECOVERY

If Ollama stops:

Restart.

If Worker crashes:

Restart Worker.

If Provider fails:

Switch Provider if allowed.

If Dashboard disconnects:

Reconnect.

If Voice stops:

Recover.

MARK should survive failures gracefully.

---

# DESIGN RULES

One responsibility per module.

No circular dependencies.

No hidden communication.

No duplicated logic.

No direct worker-to-worker communication.

No direct provider access.

Everything flows through MARK.

---

# THE GOLDEN ARCHITECTURE RULE

Every new feature must answer:

"Where does this belong?"

If the answer is unclear,

the architecture needs improvement before code is written.

Architecture always comes before implementation.

---

END OF ARCHITECTURE.md