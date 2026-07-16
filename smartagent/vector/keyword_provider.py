"""
KeywordProvider — in-memory TF-IDF keyword search.

Zero external dependencies.  Fast for small-to-medium corpora (<100k docs).
Used as the default VECTOR_PROVIDER when no vector DB is configured.

Algorithm: TF-IDF with cosine similarity, pure Python.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from smartagent.vector.base import VectorProvider, SearchResult


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class _Doc:
    id:        str
    text:      str
    metadata:  dict[str, Any]
    tf:        dict[str, float] = field(default_factory=dict)


class KeywordProvider(VectorProvider):
    """
    Pure-Python keyword search backed by TF-IDF.

    Thread-safe for concurrent reads; writes acquire a lock.
    """

    def __init__(self) -> None:
        self._docs: dict[str, _Doc] = {}
        self._df: Counter[str] = Counter()  # document frequency
        self._lock = threading.RLock()

    # ── Internal ───────────────────────────────────────────────────────────

    def _rebuild_df(self) -> None:
        self._df.clear()
        for doc in self._docs.values():
            for term in set(doc.tf.keys()):
                self._df[term] += 1

    def _tfidf_vec(self, tf: dict[str, float]) -> dict[str, float]:
        n = len(self._docs) or 1
        return {
            t: freq * math.log((n + 1) / (self._df.get(t, 0) + 1))
            for t, freq in tf.items()
        }

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        dot = sum(a.get(t, 0.0) * v for t, v in b.items())
        mag_a = math.sqrt(sum(v * v for v in a.values())) or 1.0
        mag_b = math.sqrt(sum(v * v for v in b.values())) or 1.0
        return dot / (mag_a * mag_b)

    # ── VectorProvider interface ───────────────────────────────────────────

    def add(
        self,
        texts:     list[str],
        ids:       list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        if metadatas is None:
            metadatas = [{} for _ in texts]
        with self._lock:
            for text, doc_id, meta in zip(texts, ids, metadatas):
                tokens = _tokenize(text)
                total  = len(tokens) or 1
                tf     = {t: cnt / total for t, cnt in Counter(tokens).items()}
                self._docs[doc_id] = _Doc(id=doc_id, text=text, metadata=meta, tf=tf)
            self._rebuild_df()

    def search(self, query: str, n: int = 5) -> list[SearchResult]:
        with self._lock:
            q_tokens = _tokenize(query)
            if not q_tokens or not self._docs:
                return []
            total = len(q_tokens)
            q_tf  = {t: cnt / total for t, cnt in Counter(q_tokens).items()}
            q_vec = self._tfidf_vec(q_tf)

            scored = []
            for doc in self._docs.values():
                d_vec = self._tfidf_vec(doc.tf)
                score = self._cosine(q_vec, d_vec)
                if score > 0:
                    scored.append((score, doc))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                SearchResult(id=doc.id, text=doc.text, score=round(sc, 4), metadata=doc.metadata)
                for sc, doc in scored[:n]
            ]

    def delete(self, ids: list[str]) -> None:
        with self._lock:
            for doc_id in ids:
                self._docs.pop(doc_id, None)
            self._rebuild_df()

    def count(self) -> int:
        with self._lock:
            return len(self._docs)

    def clear(self) -> None:
        with self._lock:
            self._docs.clear()
            self._df.clear()
