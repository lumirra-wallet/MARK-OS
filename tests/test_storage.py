"""
Milestone 2 — Storage layer tests. Extended in B5 for MongoDB.

Covers:
  StorageRecord           — dataclass fields, to_dict(), timestamps
  StorageProvider         — ABC helpers: get_or_default, exists, clear_namespace, health
  LocalStorageProvider    — full CRUD, overwrite, thread safety, persistence, health
  PostgresStorageProvider — full CRUD + health via mocked SQLAlchemy engine
  MongoStorageProvider    — full CRUD + health via mocked pymongo client
  storage factory         — provider selection, singleton, reset_storage
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── Shared SQLAlchemy mock ────────────────────────────────────────────────────
#
# sqlalchemy is not installed in this environment.  Any method that does
# ``from sqlalchemy import text`` would fail without a sys.modules patch.
# We inject a minimal mock so tests can focus on the provider logic.

@pytest.fixture()
def sa_mock():
    """Inject a mock sqlalchemy module so runtime imports succeed."""
    sa          = MagicMock()
    sa.text     = lambda s: s          # text("SQL") → "SQL" (a no-op pass-through)
    sa.create_engine = MagicMock()
    with patch.dict(sys.modules, {"sqlalchemy": sa, "sqlalchemy.orm": MagicMock()}):
        yield sa


# ── Shared pymongo mock ───────────────────────────────────────────────────────
#
# pymongo is not installed in this environment.  Any method that does
# ``from pymongo import MongoClient`` would fail without a sys.modules patch.

@pytest.fixture()
def pymongo_mock():
    """Inject a mock pymongo module so runtime imports succeed."""
    pm = MagicMock()
    with patch.dict(sys.modules, {"pymongo": pm}):
        yield pm


def _make_mongo_client(find_one=None, find_results=None, delete_count=1):
    """Build a minimal pymongo MongoClient/db/collection mock chain."""
    collection = MagicMock()
    collection.find_one.return_value = find_one
    collection.find.return_value.sort.return_value = iter(find_results or [])
    collection.delete_one.return_value = MagicMock(deleted_count=delete_count)

    db = MagicMock()
    db.__getitem__.return_value = collection

    client = MagicMock()
    client.__getitem__.return_value = db
    client.admin.command = MagicMock()
    return client, db, collection


def _make_engine(rows: list | None = None, rowcount: int = 1):
    """Build a minimal SQLAlchemy engine/connection mock."""
    result   = MagicMock()
    result.fetchone.return_value  = (rows[0] if rows else None)
    result.fetchall.return_value  = (rows or [])
    result.scalar.return_value    = (len(rows) if rows else 0)
    result.rowcount               = rowcount

    conn = MagicMock()
    conn.execute.return_value     = result
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__  = MagicMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value   = conn
    return engine, conn, result


# ═══════════════════════════════════════════════════════════════════════════════
# StorageRecord
# ═══════════════════════════════════════════════════════════════════════════════

class TestStorageRecord:
    def test_fields(self):
        from smartagent.storage.base import StorageRecord
        r = StorageRecord(namespace="ns", key="k", value={"x": 1})
        assert r.namespace == "ns"
        assert r.key       == "k"
        assert r.value     == {"x": 1}

    def test_to_dict_has_all_keys(self):
        from smartagent.storage.base import StorageRecord
        d = StorageRecord(namespace="n", key="k", value=42).to_dict()
        for field in ("namespace", "key", "value", "created_at", "updated_at"):
            assert field in d

    def test_to_dict_roundtrip(self):
        from smartagent.storage.base import StorageRecord
        r = StorageRecord(namespace="a", key="b", value=[1, 2, 3])
        d = r.to_dict()
        assert d["namespace"] == "a"
        assert d["key"]       == "b"
        assert d["value"]     == [1, 2, 3]

    def test_timestamps_auto_set(self):
        from smartagent.storage.base import StorageRecord
        r = StorageRecord(namespace="n", key="k", value=None)
        assert "T" in r.created_at     # ISO 8601
        assert "T" in r.updated_at

    def test_timestamps_overridable(self):
        from smartagent.storage.base import StorageRecord
        r = StorageRecord(namespace="n", key="k", value=None,
                          created_at="2024-01-01T00:00:00+00:00",
                          updated_at="2024-06-01T00:00:00+00:00")
        assert r.created_at.startswith("2024-01-01")

    def test_value_types(self):
        from smartagent.storage.base import StorageRecord
        for val in (None, 42, 3.14, True, [1, 2], {"a": 1}):
            r = StorageRecord(namespace="s", key="k", value=val)
            assert r.value == val


# ═══════════════════════════════════════════════════════════════════════════════
# StorageProvider ABC helpers  (exercised through LocalStorageProvider)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStorageProviderHelpers:
    @pytest.fixture
    def store(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        s = LocalStorageProvider(storage_dir=tmp_path / "store")
        s.initialize()
        return s

    def test_get_or_default_hits(self, store):
        store.set("ns", "k", 99)
        assert store.get_or_default("ns", "k", 0) == 99

    def test_get_or_default_misses(self, store):
        assert store.get_or_default("ns", "missing", "fallback") == "fallback"

    def test_exists_true(self, store):
        store.set("ns", "k", "v")
        assert store.exists("ns", "k") is True

    def test_exists_false(self, store):
        assert store.exists("ns", "nope") is False

    def test_clear_namespace_returns_count(self, store):
        store.set("ns", "a", 1); store.set("ns", "b", 2); store.set("ns", "c", 3)
        assert store.clear_namespace("ns") == 3
        assert store.list_keys("ns") == []

    def test_clear_namespace_empty(self, store):
        assert store.clear_namespace("empty_ns") == 0

    def test_clear_namespace_leaves_other_ns(self, store):
        store.set("ns1", "k", 1); store.set("ns2", "k", 2)
        store.clear_namespace("ns1")
        assert store.exists("ns2", "k")


# ═══════════════════════════════════════════════════════════════════════════════
# LocalStorageProvider
# ═══════════════════════════════════════════════════════════════════════════════

class TestLocalStorageCRUD:
    @pytest.fixture
    def store(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        s = LocalStorageProvider(storage_dir=tmp_path / "local")
        s.initialize()
        return s

    def test_set_and_get(self, store):
        store.set("chat", "msg1", {"role": "user", "content": "hello"})
        assert store.get("chat", "msg1") == {"role": "user", "content": "hello"}

    def test_get_missing_none(self, store):
        assert store.get("chat", "nonexistent") is None

    def test_overwrite_updates_value(self, store):
        store.set("s", "k", "light"); store.set("s", "k", "dark")
        assert store.get("s", "k") == "dark"

    def test_overwrite_preserves_created_at(self, store):
        store.set("ns", "k", "first")
        t_before = store.list_records("ns")[0].created_at
        time.sleep(0.01)
        store.set("ns", "k", "second")
        assert store.list_records("ns")[0].created_at == t_before

    def test_delete_existing_returns_true(self, store):
        store.set("ns", "k", "v")
        assert store.delete("ns", "k") is True

    def test_delete_missing_returns_false(self, store):
        assert store.delete("ns", "nothere") is False

    def test_delete_removes_key(self, store):
        store.set("ns", "k", "v"); store.delete("ns", "k")
        assert store.get("ns", "k") is None

    def test_list_keys_empty(self, store):
        assert store.list_keys("empty") == []

    def test_list_keys_all_returned(self, store):
        for k in ("a", "b", "c"):
            store.set("ns", k, k)
        assert sorted(store.list_keys("ns")) == ["a", "b", "c"]

    def test_list_keys_namespace_isolation(self, store):
        store.set("ns1", "x", 1); store.set("ns2", "y", 2)
        assert store.list_keys("ns1") == ["x"]
        assert store.list_keys("ns2") == ["y"]

    def test_list_records_type(self, store):
        from smartagent.storage.base import StorageRecord
        store.set("ns", "k", "val")
        recs = store.list_records("ns")
        assert len(recs) == 1
        assert isinstance(recs[0], StorageRecord)
        assert recs[0].key == "k"; assert recs[0].value == "val"

    def test_list_records_namespace_field(self, store):
        store.set("myns", "k", "v")
        assert store.list_records("myns")[0].namespace == "myns"

    def test_list_records_has_timestamps(self, store):
        store.set("ns", "k", "v")
        rec = store.list_records("ns")[0]
        assert rec.created_at; assert rec.updated_at

    def test_scalar_types(self, store):
        for k, v in [("i", 42), ("f", 3.14), ("b", True), ("l", [1,2]), ("d", {"a":1}), ("n", None)]:
            store.set("ns", k, v)
            assert store.get("ns", k) == v

    def test_persists_across_instances(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        d = tmp_path / "persist"
        LocalStorageProvider(storage_dir=d).tap(lambda s: (s.initialize(), s.set("ns", "k", "persisted")))
        # Reload from same dir
        s2 = LocalStorageProvider(storage_dir=d); s2.initialize()
        assert s2.get("ns", "k") == "persisted"

    def test_corrupt_file_returns_empty(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        d = tmp_path / "corrupt"; d.mkdir()
        (d / "ns.json").write_text("NOT JSON {{{{")
        store = LocalStorageProvider(storage_dir=d)
        assert store.list_keys("ns") == []


# ── Patch tap() onto LocalStorageProvider for the persistence test ─────────────

from smartagent.storage.local_storage import LocalStorageProvider as _LSP

def _tap(self, fn):
    fn(self)
    return self
_LSP.tap = _tap   # type: ignore[attr-defined]


class TestLocalStorageHealth:
    def test_health_ok(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        s = LocalStorageProvider(storage_dir=tmp_path / "h"); s.initialize()
        h = s.health()
        assert h["status"] == "ok"
        assert h["provider"] == "local"
        assert "dir" in h

    def test_health_creates_dir(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        d = tmp_path / "new_dir"
        LocalStorageProvider(storage_dir=d).health()
        assert d.exists()


class TestLocalStorageThreadSafety:
    def test_concurrent_writes_no_errors(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        store = LocalStorageProvider(storage_dir=tmp_path / "t"); store.initialize()
        errors: list = []

        def write(n):
            try:
                for i in range(20):
                    store.set("ns", f"k{n}_{i}", n * 100 + i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write, args=(t,)) for t in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert errors == []
        assert len(store.list_keys("ns")) == 5 * 20


# ═══════════════════════════════════════════════════════════════════════════════
# PostgresStorageProvider  (mocked SQLAlchemy)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPostgresStorageInit:
    def test_init_stores_url(self):
        from smartagent.storage.postgres_storage import PostgresStorageProvider
        p = PostgresStorageProvider("postgresql://user:pass@host/db")
        assert "host/db" in p._url
        assert p._engine is None

    def test_uninitialized_get_raises(self, sa_mock):
        from smartagent.storage.postgres_storage import PostgresStorageProvider
        p = PostgresStorageProvider("postgresql://x/y")
        # _engine is None → _engine_or_raise should raise RuntimeError
        with pytest.raises(RuntimeError, match="not initialized"):
            p.get("ns", "k")

    def test_initialize_missing_sqlalchemy_raises(self, monkeypatch):
        import builtins
        real = builtins.__import__
        def fake(name, *a, **kw):
            if name == "sqlalchemy": raise ImportError("no sqlalchemy")
            return real(name, *a, **kw)
        monkeypatch.setattr(builtins, "__import__", fake)
        from smartagent.storage.postgres_storage import PostgresStorageProvider
        p = PostgresStorageProvider("postgresql://x/y"); p._engine = None
        with pytest.raises(RuntimeError, match="pip install sqlalchemy"):
            p.initialize()

    def test_initialize_sets_engine(self, sa_mock):
        from smartagent.storage.postgres_storage import PostgresStorageProvider
        engine, conn, _ = _make_engine()
        sa_mock.create_engine.return_value = engine
        p = PostgresStorageProvider("postgresql://x/y")
        p.initialize()
        assert p._engine is engine


class TestPostgresStorageCRUD:
    """All SQLAlchemy calls go through the sa_mock fixture."""

    @pytest.fixture(autouse=True)
    def _sa(self, sa_mock):
        self._sa_mock = sa_mock

    @pytest.fixture
    def store(self):
        from smartagent.storage.postgres_storage import PostgresStorageProvider
        p = PostgresStorageProvider("postgresql://x/y")
        return p

    def _wire(self, store, rows=None, rowcount=1):
        engine, conn, result = _make_engine(rows, rowcount)
        store._engine = engine
        return engine, conn, result

    # ── get ──────────────────────────────────────────────────────────────────

    def test_get_existing(self, store):
        self._wire(store, rows=[(json.dumps({"k": "v"}),)])
        assert store.get("ns", "k") == {"k": "v"}

    def test_get_missing_returns_none(self, store):
        engine, conn, result = self._wire(store)
        result.fetchone.return_value = None
        assert store.get("ns", "missing") is None

    def test_get_scalar_int(self, store):
        self._wire(store, rows=[(json.dumps(42),)])
        assert store.get("ns", "k") == 42

    # ── set ──────────────────────────────────────────────────────────────────

    def test_set_calls_execute_and_commit(self, store):
        _, conn, _ = self._wire(store)
        store.set("ns", "k", {"x": 1})
        assert conn.execute.called
        assert conn.commit.called

    def test_set_serializes_value(self, store):
        _, conn, _ = self._wire(store)
        store.set("ns", "k", [1, 2, 3])
        params = conn.execute.call_args[0][1]
        assert json.loads(params["v"]) == [1, 2, 3]

    def test_set_passes_namespace_and_key(self, store):
        _, conn, _ = self._wire(store)
        store.set("myns", "mykey", "val")
        params = conn.execute.call_args[0][1]
        assert params["ns"] == "myns"
        assert params["k"]  == "mykey"

    # ── delete ────────────────────────────────────────────────────────────────

    def test_delete_returns_true_when_row_deleted(self, store):
        self._wire(store, rowcount=1)
        assert store.delete("ns", "k") is True

    def test_delete_returns_false_when_no_row(self, store):
        _, _, result = self._wire(store, rowcount=0)
        result.rowcount = 0
        assert store.delete("ns", "k") is False

    def test_delete_calls_commit(self, store):
        _, conn, _ = self._wire(store, rowcount=1)
        store.delete("ns", "k")
        assert conn.commit.called

    # ── list_keys ─────────────────────────────────────────────────────────────

    def test_list_keys_returns_keys(self, store):
        self._wire(store, rows=[("alpha",), ("beta",), ("gamma",)])
        assert store.list_keys("ns") == ["alpha", "beta", "gamma"]

    def test_list_keys_empty(self, store):
        self._wire(store, rows=[])
        assert store.list_keys("ns") == []

    # ── list_records ──────────────────────────────────────────────────────────

    def test_list_records_returns_storage_records(self, store):
        from smartagent.storage.base import StorageRecord
        rows = [
            ("k1", json.dumps("hello"), "2024-01-01T00:00:00+00:00", "2024-01-02T00:00:00+00:00"),
            ("k2", json.dumps(42),      "2024-02-01T00:00:00+00:00", "2024-02-02T00:00:00+00:00"),
        ]
        self._wire(store, rows=rows)
        recs = store.list_records("myns")
        assert len(recs) == 2
        assert all(isinstance(r, StorageRecord) for r in recs)
        assert recs[0].key == "k1"; assert recs[0].value == "hello"
        assert recs[1].value == 42
        assert all(r.namespace == "myns" for r in recs)

    # ── health ────────────────────────────────────────────────────────────────

    def test_health_ok(self, store):
        self._wire(store)
        h = store.health()
        assert h["status"]   == "ok"
        assert "postgres" in h["provider"]
        assert "ms" in h["message"] or "reachable" in h["message"]

    def test_health_error_on_exception(self, store):
        store._engine = MagicMock()
        store._engine.connect.side_effect = Exception("connection refused")
        h = store.health()
        assert h["status"] == "error"

    def test_health_uninitialized(self, store):
        # _engine is None
        h = store.health()
        assert h["status"] == "error"


# ═══════════════════════════════════════════════════════════════════════════════
# MongoStorageProvider  (mocked pymongo)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMongoStorageInit:
    def test_init_stores_uri_and_defaults_db_name(self):
        from smartagent.storage.mongo_storage import MongoStorageProvider
        p = MongoStorageProvider("mongodb://user:pass@host/")
        assert "host" in p._uri
        assert p._db_name == "mark"
        assert p._client is None
        assert p._collection is None

    def test_init_accepts_custom_db_name(self):
        from smartagent.storage.mongo_storage import MongoStorageProvider
        p = MongoStorageProvider("mongodb://x/", db_name="custom")
        assert p._db_name == "custom"

    def test_uninitialized_get_raises(self, pymongo_mock):
        from smartagent.storage.mongo_storage import MongoStorageProvider
        p = MongoStorageProvider("mongodb://x/")
        with pytest.raises(RuntimeError, match="not initialized"):
            p.get("ns", "k")

    def test_initialize_missing_pymongo_raises(self, monkeypatch):
        import builtins
        real = builtins.__import__
        def fake(name, *a, **kw):
            if name == "pymongo": raise ImportError("no pymongo")
            return real(name, *a, **kw)
        monkeypatch.setattr(builtins, "__import__", fake)
        from smartagent.storage.mongo_storage import MongoStorageProvider
        p = MongoStorageProvider("mongodb://x/")
        with pytest.raises(RuntimeError, match="pip install pymongo"):
            p.initialize()

    def test_initialize_sets_client_and_collection(self, pymongo_mock):
        from smartagent.storage.mongo_storage import MongoStorageProvider
        client, db, collection = _make_mongo_client()
        pymongo_mock.MongoClient.return_value = client
        p = MongoStorageProvider("mongodb://x/")
        p.initialize()
        assert p._client is client
        assert p._collection is collection
        assert collection.create_index.called

    def test_initialize_ping_failure_raises(self, pymongo_mock):
        from smartagent.storage.mongo_storage import MongoStorageProvider
        client, _, _ = _make_mongo_client()
        client.admin.command.side_effect = Exception("connection refused")
        pymongo_mock.MongoClient.return_value = client
        p = MongoStorageProvider("mongodb://x/")
        with pytest.raises(RuntimeError, match="cannot connect"):
            p.initialize()


class TestMongoStorageCRUD:
    """All pymongo calls go through the pymongo_mock fixture."""

    @pytest.fixture(autouse=True)
    def _pm(self, pymongo_mock):
        self._pymongo_mock = pymongo_mock

    @pytest.fixture
    def store(self):
        from smartagent.storage.mongo_storage import MongoStorageProvider
        return MongoStorageProvider("mongodb://x/")

    def _wire(self, store, find_one=None, find_results=None, delete_count=1):
        client, db, collection = _make_mongo_client(find_one, find_results, delete_count)
        store._client = client
        store._collection = collection
        return client, db, collection

    # ── get ──────────────────────────────────────────────────────────────────

    def test_get_existing(self, store):
        self._wire(store, find_one={"value": {"k": "v"}})
        assert store.get("ns", "k") == {"k": "v"}

    def test_get_missing_returns_none(self, store):
        self._wire(store, find_one=None)
        assert store.get("ns", "missing") is None

    def test_get_scalar(self, store):
        self._wire(store, find_one={"value": 42})
        assert store.get("ns", "k") == 42

    # ── set ──────────────────────────────────────────────────────────────────

    def test_set_calls_update_one_upsert(self, store):
        _, _, collection = self._wire(store)
        store.set("ns", "k", {"x": 1})
        assert collection.update_one.called
        _, kwargs = collection.update_one.call_args
        assert kwargs.get("upsert") is True

    def test_set_stores_value_natively_no_json_encoding(self, store):
        _, _, collection = self._wire(store)
        store.set("ns", "k", [1, 2, 3])
        args, _ = collection.update_one.call_args
        update_doc = args[1]
        assert update_doc["$set"]["value"] == [1, 2, 3]

    def test_set_passes_namespace_and_key_filter(self, store):
        _, _, collection = self._wire(store)
        store.set("myns", "mykey", "val")
        args, _ = collection.update_one.call_args
        assert args[0] == {"namespace": "myns", "key": "mykey"}

    def test_set_preserves_created_at_via_set_on_insert(self, store):
        _, _, collection = self._wire(store)
        store.set("ns", "k", "v")
        args, _ = collection.update_one.call_args
        assert "created_at" in args[1]["$setOnInsert"]
        assert "created_at" not in args[1]["$set"]

    # ── delete ────────────────────────────────────────────────────────────────

    def test_delete_returns_true_when_deleted(self, store):
        self._wire(store, delete_count=1)
        assert store.delete("ns", "k") is True

    def test_delete_returns_false_when_no_doc(self, store):
        self._wire(store, delete_count=0)
        assert store.delete("ns", "k") is False

    # ── list_keys ─────────────────────────────────────────────────────────────

    def test_list_keys_returns_keys(self, store):
        self._wire(store, find_results=[{"key": "alpha"}, {"key": "beta"}])
        assert store.list_keys("ns") == ["alpha", "beta"]

    def test_list_keys_empty(self, store):
        self._wire(store, find_results=[])
        assert store.list_keys("ns") == []

    # ── list_records ──────────────────────────────────────────────────────────

    def test_list_records_returns_storage_records(self, store):
        from smartagent.storage.base import StorageRecord
        docs = [
            {"key": "k1", "value": "hello", "created_at": "2024-01-01T00:00:00+00:00",
             "updated_at": "2024-01-02T00:00:00+00:00"},
            {"key": "k2", "value": 42, "created_at": "2024-02-01T00:00:00+00:00",
             "updated_at": "2024-02-02T00:00:00+00:00"},
        ]
        self._wire(store, find_results=docs)
        recs = store.list_records("myns")
        assert len(recs) == 2
        assert all(isinstance(r, StorageRecord) for r in recs)
        assert recs[0].key == "k1"; assert recs[0].value == "hello"
        assert recs[1].value == 42
        assert all(r.namespace == "myns" for r in recs)

    # ── health ────────────────────────────────────────────────────────────────

    def test_health_ok(self, store):
        self._wire(store)
        h = store.health()
        assert h["status"]  == "ok"
        assert h["provider"] == "mongodb"

    def test_health_error_on_exception(self, store):
        client, _, _ = self._wire(store)
        client.admin.command.side_effect = Exception("connection refused")
        h = store.health()
        assert h["status"] == "error"

    def test_health_uninitialized(self, store):
        # _client is None (never wired)
        h = store.health()
        assert h["status"] == "error"


# ═══════════════════════════════════════════════════════════════════════════════
# Storage factory
# ═══════════════════════════════════════════════════════════════════════════════

class TestStorageFactory:
    @pytest.fixture(autouse=True)
    def reset(self):
        import smartagent.storage.factory as fac
        fac.reset_storage()
        yield
        fac.reset_storage()

    def test_default_is_local(self, monkeypatch, tmp_path):
        import smartagent.storage.factory as fac
        monkeypatch.delenv("DATABASE_PROVIDER", raising=False)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "s"))
        from smartagent.storage.local_storage import LocalStorageProvider
        assert isinstance(fac.get_storage(), LocalStorageProvider)

    def test_explicit_sqlite_is_local(self, monkeypatch, tmp_path):
        import smartagent.storage.factory as fac
        monkeypatch.setenv("DATABASE_PROVIDER", "sqlite")
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "s"))
        from smartagent.storage.local_storage import LocalStorageProvider
        assert isinstance(fac.get_storage(), LocalStorageProvider)

    def test_postgres_without_url_raises(self, monkeypatch):
        import smartagent.storage.factory as fac
        monkeypatch.setenv("DATABASE_PROVIDER", "postgres")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            fac.get_storage()

    def test_postgres_selected_when_provider_set(self, monkeypatch, sa_mock):
        import smartagent.storage.factory as fac
        monkeypatch.setenv("DATABASE_PROVIDER", "postgres")
        monkeypatch.setenv("DATABASE_URL",       "postgresql://x/y")
        engine, conn, _ = _make_engine()
        sa_mock.create_engine.return_value = engine
        with patch("smartagent.storage.postgres_storage.PostgresStorageProvider.initialize"):
            store = fac.get_storage()
        from smartagent.storage.postgres_storage import PostgresStorageProvider
        assert isinstance(store, PostgresStorageProvider)

    def test_singleton(self, monkeypatch, tmp_path):
        import smartagent.storage.factory as fac
        monkeypatch.delenv("DATABASE_PROVIDER", raising=False)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "s"))
        assert fac.get_storage() is fac.get_storage()

    def test_reset_yields_new_instance(self, monkeypatch, tmp_path):
        import smartagent.storage.factory as fac
        monkeypatch.delenv("DATABASE_PROVIDER", raising=False)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "s"))
        s1 = fac.get_storage()
        fac.reset_storage()
        s2 = fac.get_storage()
        assert s1 is not s2

    def test_database_url_alone_stays_local(self, monkeypatch, tmp_path):
        """Replit auto-sets DATABASE_URL; without DATABASE_PROVIDER=postgres we stay local."""
        import smartagent.storage.factory as fac
        monkeypatch.delenv("DATABASE_PROVIDER", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://auto-replit/db")
        monkeypatch.setenv("STORAGE_DIR",  str(tmp_path / "s"))
        from smartagent.storage.local_storage import LocalStorageProvider
        assert isinstance(fac.get_storage(), LocalStorageProvider)

    def test_mongodb_without_uri_raises(self, monkeypatch):
        import smartagent.storage.factory as fac
        monkeypatch.setenv("DATABASE_PROVIDER", "mongodb")
        monkeypatch.delenv("MONGODB_URI", raising=False)
        with pytest.raises(RuntimeError, match="MONGODB_URI"):
            fac.get_storage()

    def test_mongodb_selected_when_provider_set(self, monkeypatch):
        import smartagent.storage.factory as fac
        monkeypatch.setenv("DATABASE_PROVIDER", "mongodb")
        monkeypatch.setenv("MONGODB_URI", "mongodb://x/")
        with patch("smartagent.storage.mongo_storage.MongoStorageProvider.initialize"):
            store = fac.get_storage()
        from smartagent.storage.mongo_storage import MongoStorageProvider
        assert isinstance(store, MongoStorageProvider)

    def test_mongodb_default_db_name(self, monkeypatch):
        import smartagent.storage.factory as fac
        monkeypatch.setenv("DATABASE_PROVIDER", "mongodb")
        monkeypatch.setenv("MONGODB_URI", "mongodb://x/")
        monkeypatch.delenv("MONGODB_DB_NAME", raising=False)
        with patch("smartagent.storage.mongo_storage.MongoStorageProvider.initialize"):
            store = fac.get_storage()
        assert store._db_name == "mark"

    def test_mongodb_custom_db_name(self, monkeypatch):
        import smartagent.storage.factory as fac
        monkeypatch.setenv("DATABASE_PROVIDER", "mongodb")
        monkeypatch.setenv("MONGODB_URI", "mongodb://x/")
        monkeypatch.setenv("MONGODB_DB_NAME", "custom_db")
        with patch("smartagent.storage.mongo_storage.MongoStorageProvider.initialize"):
            store = fac.get_storage()
        assert store._db_name == "custom_db"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration — LocalStorageProvider end-to-end
# ═══════════════════════════════════════════════════════════════════════════════

class TestStorageIntegration:
    def test_round_trip_complex_value(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        s = LocalStorageProvider(storage_dir=tmp_path / "i"); s.initialize()
        val = {"messages": [{"role": "user", "content": "hi"}], "meta": {"tokens": 7}}
        s.set("chat", "s1", val)
        assert s.get("chat", "s1") == val

    def test_multiple_namespaces_independent(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        s = LocalStorageProvider(storage_dir=tmp_path / "m"); s.initialize()
        for ns in ("chat", "memory", "settings"):
            s.set(ns, "k", f"{ns}_val")
        for ns in ("chat", "memory", "settings"):
            assert s.get(ns, "k") == f"{ns}_val"
        s.clear_namespace("chat")
        assert s.get("chat",   "k") is None
        assert s.get("memory", "k") == "memory_val"

    def test_exists_and_get_or_default(self, tmp_path):
        from smartagent.storage.local_storage import LocalStorageProvider
        s = LocalStorageProvider(storage_dir=tmp_path / "e"); s.initialize()
        assert not s.exists("ns", "k")
        assert s.get_or_default("ns", "k", "dflt") == "dflt"
        s.set("ns", "k", "real")
        assert s.exists("ns", "k")
        assert s.get_or_default("ns", "k", "dflt") == "real"
