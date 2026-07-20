"""
livekit_token.py — LiveKit JWT token generation using pyjwt.

Implements the LiveKit VideoGrant token format (HS256, standard JWT).
No livekit-api dependency needed — pyjwt is already in requirements.minimal.txt.
"""

from __future__ import annotations

import os
import time

import jwt  # pyjwt


LIVEKIT_ROOM   = os.environ.get("LIVEKIT_ROOM", "mark-presence")
_DEFAULT_TTL   = 7200  # 2 hours


def _key_and_secret() -> tuple[str, str]:
    key    = os.environ.get("LIVEKIT_API_KEY")
    secret = os.environ.get("LIVEKIT_API_SECRET")
    if not key or not secret:
        raise RuntimeError(
            "LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set. "
            "Run `python -m smartagent.server.livekit_setup` to generate them."
        )
    return key, secret


def create_browser_token(identity: str = "browser", ttl: int = _DEFAULT_TTL) -> str:
    """Token for the human participant: publish mic, subscribe to MARK's audio."""
    key, secret = _key_and_secret()
    now = int(time.time())
    payload = {
        "iss": key,
        "sub": identity,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "video": {
            "room":           LIVEKIT_ROOM,
            "roomJoin":       True,
            "canPublish":     True,
            "canSubscribe":   True,
            "canPublishData": True,
        },
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def create_agent_token(identity: str = "mark-agent", ttl: int = _DEFAULT_TTL) -> str:
    """Token for MARK's backend agent: publish TTS audio, subscribe to browser mic."""
    key, secret = _key_and_secret()
    now = int(time.time())
    payload = {
        "iss": key,
        "sub": identity,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "video": {
            "room":           LIVEKIT_ROOM,
            "roomJoin":       True,
            "canPublish":     True,
            "canSubscribe":   True,
            "canPublishData": True,
            "hidden":         True,   # agent doesn't appear in participant list
        },
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def livekit_configured() -> bool:
    """True when both API key and secret are present in the environment."""
    return bool(
        os.environ.get("LIVEKIT_API_KEY") and
        os.environ.get("LIVEKIT_API_SECRET")
    )
