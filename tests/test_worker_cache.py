"""Tests for smartagent.performance.worker_cache — v2.0."""

import pytest
from smartagent.performance.worker_cache import WorkerCache, get_global_cache


class TestWorkerCache:
    def _cache(self, max_size=16):
        return WorkerCache(max_size=max_size)

    def test_get_miss_returns_none(self):
        c = self._cache()
        assert c.get("nonexistent") is None

    def test_put_and_get(self):
        c = self._cache()
        c.put("k1", "hello")
        assert c.get("k1") == "hello"

    def test_miss_increments_stat(self):
        c = self._cache()
        c.get("absent")
        assert c.stats.misses == 1

    def test_hit_increments_stat(self):
        c = self._cache()
        c.put("k", "v")
        c.get("k")
        assert c.stats.hits == 1

    def test_put_increments_puts(self):
        c = self._cache()
        c.put("k", "v")
        assert c.stats.puts == 1

    def test_hit_rate_zero_initially(self):
        c = self._cache()
        assert c.stats.hit_rate == 0.0

    def test_hit_rate_after_hit(self):
        c = self._cache()
        c.put("k", "v")
        c.get("k")  # hit
        c.get("missing")  # miss
        assert c.stats.hit_rate == 0.5

    def test_len_empty(self):
        c = self._cache()
        assert len(c) == 0

    def test_len_after_put(self):
        c = self._cache()
        c.put("a", "1")
        c.put("b", "2")
        assert len(c) == 2

    def test_contains(self):
        c = self._cache()
        c.put("k", "v")
        assert "k" in c
        assert "missing" not in c

    def test_invalidate_existing(self):
        c = self._cache()
        c.put("k", "v")
        removed = c.invalidate("k")
        assert removed is True
        assert c.get("k") is None

    def test_invalidate_missing(self):
        c = self._cache()
        assert c.invalidate("nonexistent") is False

    def test_clear(self):
        c = self._cache()
        c.put("a", "1")
        c.put("b", "2")
        c.clear()
        assert len(c) == 0

    def test_clear_resets_stats(self):
        c = self._cache()
        c.put("k", "v")
        c.get("k")
        c.clear()
        assert c.stats.hits == 0
        assert c.stats.puts == 0

    def test_eviction_at_capacity(self):
        c = self._cache(max_size=3)
        c.put("a", "1")
        c.put("b", "2")
        c.put("c", "3")
        c.put("d", "4")  # should evict oldest
        assert len(c) == 3
        assert "d" in c

    def test_make_key_deterministic(self):
        c = self._cache()
        k1 = c.make_key("Build a REST API", "Implementation", "Coding Worker", "llama3")
        k2 = c.make_key("Build a REST API", "Implementation", "Coding Worker", "llama3")
        assert k1 == k2

    def test_make_key_different_goal(self):
        c = self._cache()
        k1 = c.make_key("Build REST API", "Impl", "Coding", "llama3")
        k2 = c.make_key("Build GraphQL API", "Impl", "Coding", "llama3")
        assert k1 != k2

    def test_make_key_case_insensitive_goal(self):
        c = self._cache()
        k1 = c.make_key("BUILD A REST API", "Impl", "Coding", "llama3")
        k2 = c.make_key("build a rest api", "Impl", "Coding", "llama3")
        assert k1 == k2

    def test_make_key_none_model(self):
        c = self._cache()
        k = c.make_key("goal", "task", "worker", None)
        assert isinstance(k, str)
        assert len(k) == 32  # MD5 hex digest


class TestGetGlobalCache:
    def test_returns_cache(self):
        cache = get_global_cache()
        assert isinstance(cache, WorkerCache)

    def test_singleton(self):
        c1 = get_global_cache()
        c2 = get_global_cache()
        assert c1 is c2
