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

Storage isolation
─────────────────
DATABASE_PROVIDER / MONGODB_URI are the same kind of live, process-level
environment variable — and unlike ACTIVE_PROVIDER, a test that silently
picks up the real value doesn't just get a wrong assertion, it writes real
documents into a real, shared production database. DevPipeline.run() calls
get_storage() directly (engineering_memory persistence, added for B6), so
any test that constructs a real DevPipeline and calls .run() without an
explicit get_storage() mock will hit whatever backend DATABASE_PROVIDER
points at in the ambient environment.

``isolate_storage_env`` (autouse=True) forces every test back to the local
JSON backend by default: it clears the provider-selection vars, patches
LocalStorageProvider's default directory to a per-test tmp_path (note: the
STORAGE_DIR env var alone is NOT enough — local_storage.py reads it into a
module-level constant at import time, so it's already frozen by the time
any test runs; the fixture patches that constant directly instead), and
resets the get_storage() singleton before and after each test so a
provider selected by one test can't leak into the next. Tests that need to
exercise a specific backend do so explicitly (see tests/test_storage.py's
mocked-provider fixtures).
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


# ---------------------------------------------------------------------------
# Storage environment isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_storage_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """
    Force every test onto an isolated, disposable local-JSON storage backend.

    Clears DATABASE_PROVIDER/DATABASE_URL/MONGODB_URI/MONGODB_DB_NAME so a
    real Postgres/Mongo URI set in the ambient environment can never be
    picked up by a test that forgets to mock get_storage() — see the
    module docstring for why this matters more than it looks like it should.
    Also resets the storage factory's module-level singleton before and
    after the test, since a provider instance created by an earlier test
    would otherwise be reused for the rest of the process regardless of
    what these env vars say.
    """
    monkeypatch.delenv("DATABASE_PROVIDER", raising=False)
    monkeypatch.delenv("DATABASE_URL",      raising=False)
    monkeypatch.delenv("MONGODB_URI",       raising=False)
    monkeypatch.delenv("MONGODB_DB_NAME",   raising=False)

    import smartagent.storage.local_storage as local_storage_module
    monkeypatch.setattr(
        local_storage_module, "_DEFAULT_DIR", tmp_path / "mark_storage_test",
    )

    import smartagent.storage.factory as storage_factory
    storage_factory.reset_storage()
    yield
    storage_factory.reset_storage()
