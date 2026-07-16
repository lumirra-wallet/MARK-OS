"""
Pydantic request/response models for the MARK web server.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    """Start a MARK software-engineering run."""
    goal: str = Field(..., description="Natural-language goal for MARK to achieve.")
    workspace: str = Field(".", description="Absolute or relative path to the project workspace.")
    test_cmd: str = Field("pytest", description="Shell command to run tests.")
    max_iterations: int = Field(5, ge=1, le=20)


class ApproveRequest(BaseModel):
    """Approve a pending permission request."""
    request_id: str = Field("", description="ID of the permission to approve.  Empty = approve latest.")
    always: bool = Field(False, description="Always approve this operation type without asking again.")


class DenyRequest(BaseModel):
    """Deny a pending permission request."""
    request_id: str = Field("", description="ID of the permission to deny.  Empty = deny latest.")
    reason: str = Field("", description="Optional reason shown in the UI.")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


class WorkerInfo(BaseModel):
    name: str
    status: str                  # "idle" | "running" | "completed" | "failed"
    task_title: str = ""
    elapsed: float = 0.0
    confidence: float = 0.0


class StatusResponse(BaseModel):
    running: bool
    goal: str = ""
    workspace: str = "."
    elapsed: float = 0.0
    workers: list[WorkerInfo] = []
    cancel_requested: bool = False


class ProjectFile(BaseModel):
    path: str
    name: str
    size: int = 0
    content: str | None = None     # populated when ?file=<path> is given


class ProjectResponse(BaseModel):
    workspace: str
    files: list[ProjectFile] = []


class PendingPermissionInfo(BaseModel):
    request_id: str
    operation: str
    path: str
    diff: str = ""


class PermissionsResponse(BaseModel):
    pending: list[PendingPermissionInfo] = []


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------

class VoiceStartRequest(BaseModel):
    """Start the voice pipeline."""
    mode: str = Field("push_to_talk", description="push_to_talk | continuous | wake_word")


class VoiceSpeakRequest(BaseModel):
    """Synthesise text using TTS."""
    text: str = Field(..., description="Text to speak aloud.")


class VoiceSettingsUpdateRequest(BaseModel):
    """Partially update VoiceSettings (all fields optional)."""
    mode:           str   | None = None
    wake_phrase:    str   | None = None
    whisper_model:  str   | None = None
    language:       str   | None = None
    tts_voice:      str   | None = None
    tts_speed:      float | None = None
    muted:          bool  | None = None
    auto_submit:    bool  | None = None
    vad_threshold:  float | None = None
    silence_frames: int   | None = None


class VoiceStatusResponse(BaseModel):
    state:   str
    running: bool
    settings: dict[str, Any] = {}


class VoiceTranscribeResponse(BaseModel):
    text: str
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# WebSocket event envelope
# ---------------------------------------------------------------------------

class EventMessage(BaseModel):
    """JSON envelope streamed over the WebSocket."""
    type: str = "event"          # always "event" for now
    name: str                    # event name, e.g. "WorkerStarted"
    payload: dict[str, Any] = {}
    timestamp: str = ""
