"""
MARK Web Server — Phase 1.

Thin FastAPI layer over the existing MARK backend.  All intelligence stays
in the existing Python subsystems; this package only adds:

  - REST endpoints  (smartagent.server.api)
  - WebSocket stream (smartagent.server.websocket)
  - Event bridge    (smartagent.server.events)
  - Permission gate (smartagent.server.permissions)
  - Pydantic models (smartagent.server.models)

Start with::

    uvicorn smartagent.server.app:app --reload

or via the workspace script::

    pnpm run mark:server
"""
