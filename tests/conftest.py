"""
Global pytest configuration for the MARK test suite.

Provider isolation
──────────────────
ACTIVE_PROVIDER and GITHUB_TOKEN are live Replit environment variables in
production.  Tests that check "no active model" or "ollama default" behavior
would break whenever those vars are set in the environment that runs the tests.

The ``isolate_provider_env`` fixture (autouse=True) clears both vars for every
test by default.  Tests that need a specific provider can override explicitly:

    def test_github_chat(monkeypatch):
        monkeypatch.setenv("ACTIVE_PROVIDER", "github")
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        ...

    @pytest.mark.provider("github")
    def test_requires_github(monkeypatch): ...   # sets vars via the mark
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Provider environment isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Clear provider-selection environment variables before every test.

    This ensures tests that verify "no active model" or "ollama is the
    fallback" behaviour are not broken by ACTIVE_PROVIDER=github being set
    in the Replit environment at the process level.

    Tests that explicitly need a provider set it themselves via monkeypatch
    inside the test body (monkeypatch is function-scoped so the reset happens
    automatically on teardown).
    """
    monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN",    raising=False)
