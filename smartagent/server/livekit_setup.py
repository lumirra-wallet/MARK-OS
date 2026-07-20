"""
livekit_setup.py — One-time setup helper for MARK's self-hosted LiveKit.

Run once to generate and print the three LiveKit secrets that must be stored
as Replit Secrets (or .env entries):

    python -m smartagent.server.livekit_setup

It never writes secrets to files — it prints them for the operator to store
in the Replit Secrets panel (or wherever their secret store lives).
"""

from __future__ import annotations

import os
import secrets
import sys


REQUIRED = ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_URL")


def check() -> dict[str, str | None]:
    return {k: os.environ.get(k) for k in REQUIRED}


def generate() -> None:
    present = check()
    missing = [k for k, v in present.items() if not v]

    if not missing:
        print("✓  All LiveKit secrets are already set.")
        for k, v in present.items():
            masked = v[:6] + "…" if v else "(not set)"
            print(f"   {k} = {masked}")
        return

    print("The following LiveKit secrets need to be set:\n")

    key    = present.get("LIVEKIT_API_KEY")    or f"mark-key-{secrets.token_hex(8)}"
    secret = present.get("LIVEKIT_API_SECRET") or secrets.token_urlsafe(40)
    url    = present.get("LIVEKIT_URL")        or "ws://localhost:7880"

    values = {
        "LIVEKIT_API_KEY":    key,
        "LIVEKIT_API_SECRET": secret,
        "LIVEKIT_URL":        url,
    }

    for k in missing:
        v = values[k]
        print(f"  {k}={v}")

    print(
        "\nCopy each line above into Replit Secrets (or your .env file).\n"
        "The LIVEKIT_URL value above is correct for self-hosted mode.\n"
        "For LiveKit Cloud, replace it with your cloud project's WSS URL."
    )


if __name__ == "__main__":
    generate()
    sys.exit(0)
