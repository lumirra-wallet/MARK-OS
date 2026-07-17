"""
Milestone 2 — Vector layer tests.

Covers:
  SearchResult       — dataclass fields
  VectorProvider     — ABC helpers: health, clear (raises by default), initialize
  KeywordProvider    — TF-IDF: add, search relevance, delete, count, clear, thread safety
  ChromaProvider     — full CRUD via mocked chromadb
  PGVectorProvider   — full CRUD via mocked SQLAlchemy + mocked embed
  vector factory     — provider selection, singleton, reset_vector_store

TF-IDF note:
  IDF = log((N+1)/(df+1)).  With a single document, IDF = log(1) = 0, so the
  cosine similarity is 0 and search returns empty.  Any test that calls
  search() must therefore index at least TWO documents so that the query term
  appears in some but not all of them.  Tests that only care about count /
  delete / structure use a multi-doc corpus or avoid calling search().
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest


# ── SQLAlchemy mock (pgvector uses `from sqlalchemy import text` inside methods)

@pytest.fixture()
def sa_mock():
    sa       = MagicMock()
    sa.text  = lambda s: s   # pass-through so SQL strings reach the mock conn
    sa.create_engine = MagicMock()
    with patch.dict(sys.modules, {"sqlalchemy": sa, "sqlalchemy.orm": MagicMock()}):
        yield sa


# ═══════════════════════════════════════════════════════════════════════════════
# SearchResult
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchResult:
    def test_fields(self):
        from smartagent.vector.base import SearchResult
        r = SearchResult(id="d1", text="hello world", score=0.95)
        assert r.id == "d1"; assert r.text == "hello world"; assert r.score == 0.95

    def test_default_metadata_empty(self):
        from smartagent.vector.base import SearchResult
        assert SearchResult(id="x", text="t", score=0.5).metadata == {}

    def test_custom_metadata(self):
        from smartagent.vector.base import SearchResult
        r = SearchResult(id="x", text="t", score=0.5, metadata={"source": "web"})
        assert r.metadata["source"] == "web"


# ═══════════════════════════════════════════════════════════════════════════════
# VectorProvider ABC helpers  (via KeywordProvider)
# ═══════════════════════════════════════════════════════════════════════════════

class TestVectorProviderHelpers:
    @pytest.fixture
    def vs(self):
        from smartagent.vector.keyword_provider import KeywordProvider
        return KeywordProvider()

    def test_health_empty(self, vs):
        h = vs.health()
        assert h["status"] == "ok"; assert h["count"] == 0

    def test_health_with_docs(self, vs):
        vs.add(["a", "b"], ["d1", "d2"])   # two docs for valid IDF
        h = vs.health()
        assert h["status"] == "ok"; assert h["count"] == 2

    def test_initialize_noop(self, vs):
        vs.initialize()  # must not raise

    def test_repr_includes_class(self, vs):
        assert "KeywordProvider" in repr(vs)

    def test_base_clear_raises(self):
        from smartagent.vector.base import VectorProvider

        class Minimal(VectorProvider):
            def add(self, texts, ids, metadatas=None): pass
            def search(self, query, n=5): return []
            def delete(self, ids): pass
            def count(self): return 0

        with pytest.raises(NotImplementedError):
            Minimal().clear()


# ═══════════════════════════════════════════════════════════════════════════════
# KeywordProvider
# ═══════════════════════════════════════════════════════════════════════════════

# TF-IDF safe corpus helpers
_CORPUS_TEXTS = [
    "Python is a programming language used for data science",
    "JavaScript runs in the browser and on the server",
    "Rust is fast and memory safe for systems programming",
    "Go is a statically typed language from Google",
    "TypeScript adds types to JavaScript for better tooling",
]
_CORPUS_IDS = ["py", "js", "rs", "go", "ts"]


class TestKeywordProviderBasics:
    @pytest.fixture
    def vs(self):
        from smartagent.vector.keyword_provider import KeywordProvider
        return KeywordProvider()

    # ── count ────────────────────────────────────────────────────────────────

    def test_initial_count_zero(self, vs):
        assert vs.count() == 0

    def test_add_increases_count(self, vs):
        vs.add(_CORPUS_TEXTS[:2], _CORPUS_IDS[:2])
        assert vs.count() == 2

    def test_add_multiple_batches(self, vs):
        vs.add(["doc a", "doc b"], ["a", "b"])
        vs.add(["doc c"],          ["c"])
        assert vs.count() == 3

    # ── overwrite ────────────────────────────────────────────────────────────

    def test_overwrite_same_id_count_stable(self, vs):
        vs.add(["original text", "decoy document here"], ["doc", "decoy"])
        vs.add(["updated text"],                         ["doc"])
        assert vs.count() == 2   # "doc" replaced, not added

    def test_overwrite_replaces_content(self, vs):
        vs.add(["old content here", "another doc"], ["doc", "other"])
        vs.add(["new content here"],                ["doc"])
        results = vs.search("new content")
        assert results and results[0].id == "doc"

    # ── add with / without metadata ─────────────────────────────────────────

    def test_add_with_metadata(self, vs):
        # two docs so TF-IDF IDF > 0
        vs.add(
            ["python programming language", "unrelated javascript topic"],
            ["py", "js"],
            metadatas=[{"source": "docs"}, {"source": "web"}],
        )
        results = vs.search("python programming")
        assert results
        assert results[0].metadata == {"source": "docs"}

    def test_add_without_metadata_defaults_empty(self, vs):
        vs.add(["python programming", "java enterprise"], ["py", "java"])
        results = vs.search("python programming")
        assert results
        assert results[0].metadata == {}

    # ── search ranking ────────────────────────────────────────────────────────

    def test_search_returns_searchresult_objects(self, vs):
        from smartagent.vector.base import SearchResult
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        assert all(isinstance(r, SearchResult) for r in vs.search("Python programming"))

    def test_search_relevant_doc_first(self, vs):
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        results = vs.search("Python programming")
        assert results[0].id == "py"   # only "py" contains both tokens

    def test_search_respects_n_limit(self, vs):
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        assert len(vs.search("programming language", n=2)) <= 2

    def test_search_empty_store_returns_empty(self, vs):
        assert vs.search("anything") == []

    def test_search_no_token_match_returns_empty(self, vs):
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        assert vs.search("xyzzy_nonexistent_token_42") == []

    def test_search_scores_in_zero_one(self, vs):
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        for r in vs.search("language"):
            assert 0.0 <= r.score <= 1.0

    def test_search_result_has_id_and_text(self, vs):
        vs.add(
            ["my special document content", "another totally different text"],
            ["mydoc", "other"],
        )
        results = vs.search("special document")
        assert results
        r = results[0]
        assert r.id   == "mydoc"
        assert r.text == "my special document content"

    # ── delete ────────────────────────────────────────────────────────────────

    def test_delete_removes_doc(self, vs):
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        vs.delete(["py"])
        assert vs.count() == 4
        assert all(r.id != "py" for r in vs.search("Python"))

    def test_delete_missing_id_noop(self, vs):
        vs.add(["doc a", "doc b"], ["a", "b"])
        vs.delete(["nope"])     # must not raise
        assert vs.count() == 2

    def test_delete_multiple(self, vs):
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        vs.delete(["py", "rs", "ts"])
        assert vs.count() == 2
        remaining = {r.id for r in vs.search("language")}
        assert "py" not in remaining
        assert "rs" not in remaining

    # ── clear ─────────────────────────────────────────────────────────────────

    def test_clear_empties_store(self, vs):
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        vs.clear()
        assert vs.count() == 0

    def test_clear_allows_reindex(self, vs):
        vs.add(["old document content", "old second doc"], ["old1", "old2"])
        vs.clear()
        # Add fresh corpus with 2+ docs so IDF works
        vs.add(
            ["fresh brand new content", "unrelated filler document"],
            ["new1", "filler"],
        )
        assert vs.count() == 2
        results = vs.search("fresh brand new")
        assert results and results[0].id == "new1"
        # old docs must not appear
        assert all(r.id not in ("old1", "old2") for r in results)


class TestKeywordProviderTFIDF:
    """Verify TF-IDF ranking behaviour with a controlled corpus."""

    def test_rare_term_ranks_higher(self):
        from smartagent.vector.keyword_provider import KeywordProvider
        vs = KeywordProvider()
        # "zephyr" only in doc1 → high IDF
        vs.add(
            ["zephyr unique term here",
             "common word and more common words",
             "another document with common words"],
            ["rare", "common1", "common2"],
        )
        results = vs.search("zephyr unique")
        assert results[0].id == "rare"

    def test_empty_query_returns_empty(self):
        from smartagent.vector.keyword_provider import KeywordProvider
        vs = KeywordProvider()
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        assert vs.search("") == []

    def test_punctuation_stripped(self):
        from smartagent.vector.keyword_provider import KeywordProvider
        vs = KeywordProvider()
        vs.add(["hello, world!", "completely different topic here"], ["d1", "d2"])
        results = vs.search("hello world")
        assert results and results[0].id == "d1"

    def test_case_insensitive(self):
        from smartagent.vector.keyword_provider import KeywordProvider
        vs = KeywordProvider()
        vs.add(["Python Programming Language", "Java Enterprise Edition"], ["py", "java"])
        results = vs.search("python programming")
        assert results and results[0].id == "py"

    def test_single_doc_search_scores_zero(self):
        """Document the known TF-IDF behaviour: 1 doc → IDF = 0 → no results."""
        from smartagent.vector.keyword_provider import KeywordProvider
        vs = KeywordProvider()
        vs.add(["hello world"], ["d1"])
        # With only one document df==N so IDF=log(1)=0, score=0, no results returned
        assert vs.search("hello world") == []


class TestKeywordProviderThreadSafety:
    def test_concurrent_add_and_search(self):
        from smartagent.vector.keyword_provider import KeywordProvider
        vs = KeywordProvider(); errors: list = []

        def writer(start):
            try:
                for i in range(20):
                    vs.add([f"document number {start + i} text"], [f"id_{start}_{i}"])
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(20): vs.search("document")
            except Exception as e:
                errors.append(e)

        threads  = [threading.Thread(target=writer, args=(t * 20,)) for t in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert errors == []


# ═══════════════════════════════════════════════════════════════════════════════
# ChromaProvider  (mocked chromadb)
# ═══════════════════════════════════════════════════════════════════════════════

def _chroma_module(doc_count: int = 0):
    collection = MagicMock()
    collection.count.return_value = doc_count
    collection.query.return_value = {
        "ids":       [["doc1", "doc2"]],
        "documents": [["text one", "text two"]],
        "distances": [[0.1, 0.3]],
        "metadatas": [[{"src": "a"}, {}]],
    }
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    mod = MagicMock()
    mod.PersistentClient.return_value = client
    return mod, client, collection


class TestChromaProvider:
    @pytest.fixture
    def vs(self, tmp_path):
        from smartagent.vector.chroma_provider import ChromaProvider
        mod, _, collection = _chroma_module()
        with patch.dict(sys.modules, {"chromadb": mod}):
            p = ChromaProvider(path=str(tmp_path / "ch"), collection="test")
            p.initialize()
        p._collection = collection
        return p

    def test_initialize_creates_collection(self, tmp_path):
        from smartagent.vector.chroma_provider import ChromaProvider
        mod, client, _ = _chroma_module()
        with patch.dict(sys.modules, {"chromadb": mod}):
            p = ChromaProvider(path=str(tmp_path / "c"), collection="col")
            p.initialize()
        client.get_or_create_collection.assert_called_once_with("col")

    def test_initialize_missing_chromadb_raises(self, monkeypatch):
        import builtins; real = builtins.__import__
        def fake(n, *a, **k):
            if n == "chromadb": raise ImportError
            return real(n, *a, **k)
        monkeypatch.setattr(builtins, "__import__", fake)
        from smartagent.vector.chroma_provider import ChromaProvider
        p = ChromaProvider(); p._collection = None; p._client = None
        with pytest.raises(RuntimeError, match="pip install chromadb"):
            p.initialize()

    def test_count(self, vs):
        vs._collection.count.return_value = 7
        assert vs.count() == 7

    def test_delete(self, vs):
        vs.delete(["d1", "d2"])
        vs._collection.delete.assert_called_once_with(ids=["d1", "d2"])

    def test_search_returns_searchresults(self, vs):
        from smartagent.vector.base import SearchResult
        vs._embed = MagicMock(return_value=[[0.1] * 10])
        results = vs.search("hello", n=2)
        assert all(isinstance(r, SearchResult) for r in results)
        assert len(results) == 2

    def test_search_score_is_1_minus_distance(self, vs):
        vs._embed = MagicMock(return_value=[[0.1] * 10])
        results = vs.search("hello", n=2)
        assert abs(results[0].score - 0.9) < 0.01
        assert abs(results[1].score - 0.7) < 0.01

    def test_add_calls_upsert_with_ids(self, vs):
        vs._embed = MagicMock(return_value=[[0.1]*10, [0.2]*10])
        vs.add(["text a", "text b"], ["id1", "id2"])
        kw = vs._collection.upsert.call_args[1]
        assert kw["ids"]       == ["id1", "id2"]
        assert kw["documents"] == ["text a", "text b"]

    def test_add_default_metadata_empty_dicts(self, vs):
        vs._embed = MagicMock(return_value=[[0.1]*10])
        vs.add(["text"], ["id1"])
        assert vs._collection.upsert.call_args[1]["metadatas"] == [{}]

    def test_health_ok(self, vs):
        vs._collection.count.return_value = 3
        assert vs.health()["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# PGVectorProvider  (mocked SQLAlchemy + embed)
# ═══════════════════════════════════════════════════════════════════════════════

def _pg_engine(rows=None):
    result = MagicMock()
    result.fetchall.return_value = rows or []
    result.scalar.return_value   = len(rows) if rows else 0
    conn = MagicMock()
    conn.execute.return_value = result
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__  = MagicMock(return_value=False)
    engine = MagicMock()
    engine.connect.return_value = conn
    return engine, conn, result


class TestPGVectorProvider:
    @pytest.fixture(autouse=True)
    def _sa(self, sa_mock):
        self._sa = sa_mock

    @pytest.fixture
    def vs(self):
        from smartagent.vector.pgvector_provider import PGVectorProvider
        p = PGVectorProvider(database_url="postgresql://x/y")
        engine, conn, result = _pg_engine()
        p._engine = engine
        p._embed  = MagicMock(return_value=[[0.1] * 8])
        return p

    # ── init ─────────────────────────────────────────────────────────────────

    def test_init_stores_url(self):
        from smartagent.vector.pgvector_provider import PGVectorProvider
        assert PGVectorProvider(database_url="postgresql://x/y")._url == "postgresql://x/y"

    def test_init_reads_env(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://env/db")
        from smartagent.vector.pgvector_provider import PGVectorProvider
        assert PGVectorProvider()._url == "postgresql://env/db"

    def test_initialize_no_url_raises(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from smartagent.vector.pgvector_provider import PGVectorProvider
        p = PGVectorProvider(database_url="")
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            p.initialize()

    def test_initialize_missing_sqlalchemy_raises(self, monkeypatch):
        import builtins; real = builtins.__import__
        def fake(n, *a, **k):
            if n == "sqlalchemy": raise ImportError
            return real(n, *a, **k)
        monkeypatch.setattr(builtins, "__import__", fake)
        from smartagent.vector.pgvector_provider import PGVectorProvider
        p = PGVectorProvider(database_url="postgresql://x/y"); p._engine = None
        with pytest.raises(RuntimeError, match="pip install pgvector"):
            p.initialize()

    # ── count ─────────────────────────────────────────────────────────────────

    def test_count_nonzero(self, vs):
        engine, conn, result = _pg_engine()
        result.scalar.return_value = 5
        vs._engine = engine
        assert vs.count() == 5

    def test_count_zero(self, vs):
        engine, conn, result = _pg_engine(rows=[])
        result.scalar.return_value = 0
        vs._engine = engine
        assert vs.count() == 0

    # ── add ───────────────────────────────────────────────────────────────────

    def test_add_calls_execute_per_doc(self, vs):
        vs._embed = MagicMock(return_value=[[0.1]*8, [0.2]*8])
        engine, conn, _ = _pg_engine()
        vs._engine = engine
        vs.add(["text a", "text b"], ["id1", "id2"])
        assert conn.execute.call_count == 2
        assert conn.commit.called

    def test_add_serializes_metadata(self, vs):
        engine, conn, _ = _pg_engine()
        vs._engine = engine
        vs.add(["text"], ["id1"], metadatas=[{"src": "test"}])
        params = conn.execute.call_args[0][1]
        assert json.loads(params["meta"]) == {"src": "test"}

    def test_add_empty_metadata_default(self, vs):
        engine, conn, _ = _pg_engine()
        vs._engine = engine
        vs.add(["text"], ["id1"])
        params = conn.execute.call_args[0][1]
        assert json.loads(params["meta"]) == {}

    # ── search ────────────────────────────────────────────────────────────────

    def test_search_returns_searchresults(self, vs):
        from smartagent.vector.base import SearchResult
        rows = [
            ("d1", "text one", json.dumps({}),         0.9),
            ("d2", "text two", json.dumps({"x": 1}),  0.7),
        ]
        engine, conn, result = _pg_engine(rows=rows)
        result.fetchall.return_value = rows
        vs._engine = engine
        results = vs.search("query", n=2)
        assert all(isinstance(r, SearchResult) for r in results)
        assert len(results) == 2
        assert results[0].id == "d1"; assert results[0].score == round(0.9, 4)
        assert results[1].metadata == {"x": 1}

    def test_search_empty(self, vs):
        engine, conn, result = _pg_engine(rows=[])
        result.fetchall.return_value = []
        vs._engine = engine
        assert vs.search("query") == []

    # ── delete ────────────────────────────────────────────────────────────────

    def test_delete_calls_execute_per_id(self, vs):
        engine, conn, _ = _pg_engine()
        vs._engine = engine
        vs.delete(["id1", "id2", "id3"])
        assert conn.execute.call_count == 3
        assert conn.commit.called

    def test_delete_empty_list_no_execute(self, vs):
        engine, conn, _ = _pg_engine()
        vs._engine = engine
        vs.delete([])
        conn.execute.assert_not_called()

    # ── health ────────────────────────────────────────────────────────────────

    def test_health_ok(self, vs):
        engine, conn, result = _pg_engine()
        result.scalar.return_value = 0
        vs._engine = engine
        assert vs.health()["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# Vector factory
# ═══════════════════════════════════════════════════════════════════════════════

class TestVectorFactory:
    @pytest.fixture(autouse=True)
    def reset(self):
        import smartagent.vector.factory as fac
        fac.reset_vector_store()
        yield
        fac.reset_vector_store()

    def test_default_keyword_when_chromadb_missing(self, monkeypatch):
        import smartagent.vector.factory as fac
        monkeypatch.delenv("VECTOR_PROVIDER", raising=False)
        with patch.dict(sys.modules, {"chromadb": None}):
            fac.reset_vector_store()
            vs = fac.get_vector_store()
        from smartagent.vector.keyword_provider import KeywordProvider
        assert isinstance(vs, KeywordProvider)

    def test_explicit_keyword(self, monkeypatch):
        import smartagent.vector.factory as fac
        monkeypatch.setenv("VECTOR_PROVIDER", "keyword")
        from smartagent.vector.keyword_provider import KeywordProvider
        assert isinstance(fac.get_vector_store(), KeywordProvider)

    def test_pgvector_selected_by_env(self, monkeypatch, sa_mock):
        import smartagent.vector.factory as fac
        monkeypatch.setenv("VECTOR_PROVIDER", "pgvector")
        monkeypatch.setenv("DATABASE_URL",    "postgresql://x/y")
        with patch("smartagent.vector.pgvector_provider.PGVectorProvider.initialize"):
            vs = fac.get_vector_store()
        from smartagent.vector.pgvector_provider import PGVectorProvider
        assert isinstance(vs, PGVectorProvider)

    def test_chroma_selected_by_env(self, monkeypatch, tmp_path):
        import smartagent.vector.factory as fac
        monkeypatch.setenv("VECTOR_PROVIDER", "chroma")
        monkeypatch.setenv("CHROMA_PATH",     str(tmp_path / "c"))
        mod, _, _ = _chroma_module()
        with patch.dict(sys.modules, {"chromadb": mod}):
            with patch("smartagent.vector.chroma_provider.ChromaProvider.initialize"):
                vs = fac.get_vector_store()
        from smartagent.vector.chroma_provider import ChromaProvider
        assert isinstance(vs, ChromaProvider)

    def test_chroma_auto_detected_when_installed(self, monkeypatch):
        import smartagent.vector.factory as fac
        monkeypatch.delenv("VECTOR_PROVIDER", raising=False)
        mod, _, _ = _chroma_module()
        with patch.dict(sys.modules, {"chromadb": mod}):
            with patch("smartagent.vector.chroma_provider.ChromaProvider.initialize"):
                fac.reset_vector_store()
                vs = fac.get_vector_store()
        from smartagent.vector.chroma_provider import ChromaProvider
        assert isinstance(vs, ChromaProvider)

    def test_singleton(self, monkeypatch):
        import smartagent.vector.factory as fac
        monkeypatch.setenv("VECTOR_PROVIDER", "keyword")
        assert fac.get_vector_store() is fac.get_vector_store()

    def test_reset_yields_new_instance(self, monkeypatch):
        import smartagent.vector.factory as fac
        monkeypatch.setenv("VECTOR_PROVIDER", "keyword")
        vs1 = fac.get_vector_store()
        fac.reset_vector_store()
        vs2 = fac.get_vector_store()
        assert vs1 is not vs2


# ═══════════════════════════════════════════════════════════════════════════════
# Integration — KeywordProvider end-to-end
# ═══════════════════════════════════════════════════════════════════════════════

class TestVectorIntegration:
    def test_add_search_delete_cycle(self):
        from smartagent.vector.keyword_provider import KeywordProvider
        vs = KeywordProvider()
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        assert vs.count() == 5
        results = vs.search("Python data science", n=2)
        assert results[0].id == "py"
        vs.delete(["py"])
        assert vs.count() == 4
        assert all(r.id != "py" for r in vs.search("Python", n=5))

    def test_clear_and_reindex(self):
        from smartagent.vector.keyword_provider import KeywordProvider
        vs = KeywordProvider()
        vs.add(_CORPUS_TEXTS, _CORPUS_IDS)
        vs.clear()
        # Re-index a fresh 2-doc corpus so TF-IDF IDF is non-zero
        vs.add(
            ["fresh new modern content here", "unrelated background filler text"],
            ["fresh", "filler"],
        )
        assert vs.count() == 2
        results = vs.search("fresh new modern")
        assert results and results[0].id == "fresh"
        assert all(r.id not in _CORPUS_IDS for r in results)

    def test_multiple_namespaces_keyword(self):
        """Two independent KeywordProvider instances are fully isolated."""
        from smartagent.vector.keyword_provider import KeywordProvider
        vs1 = KeywordProvider()
        vs2 = KeywordProvider()
        vs1.add(_CORPUS_TEXTS, _CORPUS_IDS)
        assert vs1.count() == 5
        assert vs2.count() == 0
