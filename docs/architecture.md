# MROS Architecture Specification

## Overview

MROS (Modular Real-time Orchestration System) separates concerns into two distinct layers:

1. **MROS Core** — Stateful, long-running infrastructure
2. **Chat Adapter** — Stateless request/response boundary for LLM interactions

---

## MROS Core (Stateful Infrastructure)

**Responsibilities:**
- **Persistence** — Event sourcing, conversation history, checkpointing
- **VAD (Voice Activity Detection)** — Real-time audio stream analysis, speech segment extraction
- **Streaming** — Bidirectional audio/text streaming, backpressure handling, reconnection logic

**Characteristics:**
- Long-lived processes (daemons/services)
- Maintains session state across interactions
- Handles transport-level concerns (WebSocket, WebRTC, etc.)
- Emits domain events for audit/debugging

**Interfaces:**
- `PersistencePort` — append/read events, snapshots
- `VADPort` — process audio frames → speech segments