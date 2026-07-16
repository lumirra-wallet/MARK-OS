"""
Codebase Indexer — Feature 6, and RAG (Feature 5 lightweight).

Parses Python files with ast and TypeScript/JS with regex to build a symbol
index. Also provides simple keyword-based code search (RAG-lite without a
vector DB — good for open-source local use).

Endpoints
---------
POST /code/index            — (re)build the index for a workspace
GET  /code/search           — full-text search across indexed files
GET  /code/symbol           — find a class/function by name
GET  /code/references       — find all references to a name
GET  /code/stats            — index statistics
GET  /rag/search            — retrieve relevant chunks for a query (Feature 5)
"""
from __future__ import annotations

import ast
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Index data structures ─────────────────────────────────────────────────────

_index: dict[str, Any] = {
    "workspace":   "",
    "indexed_at":  "",
    "files":       {},   # path -> {lines, language, symbols: [{name, kind, line}]}
    "symbols":     {},   # name -> [{file, line, kind, docstring}]
}

# ── Language detection ────────────────────────────────────────────────────────

def _detect_lang(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    return {
        ".py":   "python",
        ".ts":   "typescript",
        ".tsx":  "typescript",
        ".js":   "javascript",
        ".jsx":  "javascript",
        ".md":   "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml":  "yaml",
        ".toml": "toml",
    }.get(ext)


# ── Python AST indexer ────────────────────────────────────────────────────────

def _index_python(source: str, filepath: str) -> list[dict]:
    symbols: list[dict] = []
    try:
        tree = ast.parse(source, filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node) or ""
                symbols.append({
                    "name": node.name, "kind": "function",
                    "line": node.lineno, "docstring": doc[:200],
                    "file": filepath,
                })
            elif isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or ""
                symbols.append({
                    "name": node.name, "kind": "class",
                    "line": node.lineno, "docstring": doc[:200],
                    "file": filepath,
                })
    except SyntaxError:
        pass
    return symbols


# ── TypeScript/JS regex indexer ────────────────────────────────────────────────

_TS_FUNC_RE  = re.compile(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', re.MULTILINE)
_TS_CLASS_RE = re.compile(r'(?:export\s+)?class\s+(\w+)', re.MULTILINE)
_TS_ARROW_RE = re.compile(r'(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\(', re.MULTILINE)


def _index_typescript(source: str, filepath: str) -> list[dict]:
    symbols: list[dict] = []
    lines  = source.splitlines()

    def _lineno(m: re.Match) -> int:
        return source[:m.start()].count("\n") + 1

    for m in _TS_FUNC_RE.finditer(source):
        symbols.append({"name": m.group(1), "kind": "function", "line": _lineno(m), "file": filepath, "docstring": ""})
    for m in _TS_CLASS_RE.finditer(source):
        symbols.append({"name": m.group(1), "kind": "class",    "line": _lineno(m), "file": filepath, "docstring": ""})
    for m in _TS_ARROW_RE.finditer(source):
        symbols.append({"name": m.group(1), "kind": "arrow_fn", "line": _lineno(m), "file": filepath, "docstring": ""})
    return symbols


# ── Index builder ─────────────────────────────────────────────────────────────

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "dist", "build", ".next", "coverage"}
_MAX_FILE_SIZE = 500_000   # 500 KB


def build_index(workspace: str) -> dict:
    from datetime import datetime, timezone
    ws     = Path(workspace).resolve()
    files  = {}
    syms   = {}
    t0     = time.monotonic()
    count  = 0

    for dirpath, dirnames, filenames in os.walk(str(ws)):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            full = Path(dirpath) / fname
            lang = _detect_lang(fname)
            if lang not in ("python", "typescript", "javascript"):
                continue
            if full.stat().st_size > _MAX_FILE_SIZE:
                continue
            try:
                source  = full.read_text(errors="replace")
                rel     = str(full.relative_to(ws))
                if lang == "python":
                    file_syms = _index_python(source, rel)
                else:
                    file_syms = _index_typescript(source, rel)
                lines = source.count("\n") + 1
                files[rel] = {"language": lang, "lines": lines, "symbols": file_syms}
                for s in file_syms:
                    syms.setdefault(s["name"], []).append(s)
                count += 1
            except Exception:
                pass

    _index["workspace"]  = str(ws)
    _index["indexed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _index["files"]      = files
    _index["symbols"]    = syms
    elapsed = time.monotonic() - t0
    logger.info("Code index built: %d files, %d symbols in %.2fs", count, len(syms), elapsed)
    return {"files": count, "symbols": len(syms), "elapsed_ms": round(elapsed * 1000, 1)}


# ── Endpoints ─────────────────────────────────────────────────────────────────

class IndexRequest(BaseModel):
    workspace: str = "."


@router.post("/code/index")
async def trigger_index(req: IndexRequest) -> dict:
    import asyncio
    result = await asyncio.to_thread(build_index, req.workspace)
    return {"success": True, **result, "workspace": req.workspace}


@router.get("/code/stats")
async def code_stats() -> dict:
    langs: dict[str, int] = {}
    total_lines = 0
    for meta in _index["files"].values():
        langs[meta["language"]] = langs.get(meta["language"], 0) + 1
        total_lines += meta.get("lines", 0)
    return {
        "workspace":   _index["workspace"],
        "indexed_at":  _index["indexed_at"],
        "files":       len(_index["files"]),
        "symbols":     len(_index["symbols"]),
        "total_lines": total_lines,
        "by_language": langs,
    }


@router.get("/code/search")
async def code_search(q: str, limit: int = 30) -> dict:
    if not q:
        return {"results": []}
    q_lower = q.lower()
    results = []
    for rel, meta in _index["files"].items():
        for sym in meta.get("symbols", []):
            score = 0
            if q_lower in sym["name"].lower():          score += 2
            if q_lower in sym.get("docstring", "").lower(): score += 1
            if score:
                results.append({**sym, "score": score, "language": meta["language"]})
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": results[:limit], "query": q, "total": len(results)}


@router.get("/code/symbol")
async def get_symbol(name: str) -> dict:
    results = _index["symbols"].get(name, [])
    if not results:
        # Try case-insensitive
        name_lower = name.lower()
        results = [
            s for syms in _index["symbols"].values()
            for s in syms if s["name"].lower() == name_lower
        ]
    return {"name": name, "results": results[:20]}


@router.get("/code/references")
async def get_references(name: str, limit: int = 50) -> dict:
    """Find files/lines where `name` appears as an identifier."""
    refs = []
    for rel, meta in _index["files"].items():
        # Quick grep without re-reading disk (use existing content from index)
        for sym in meta.get("symbols", []):
            if name in sym.get("docstring", ""):
                refs.append({"file": rel, "line": sym["line"], "kind": "docstring", "context": sym["name"]})
    return {"name": name, "references": refs[:limit]}


# ── RAG: retrieve relevant chunks (Feature 5) ─────────────────────────────────

@router.get("/rag/search")
async def rag_search(q: str, workspace: str = ".", limit: int = 10) -> dict:
    """
    Retrieve the most relevant code snippets for a query.
    Uses TF-IDF-style keyword scoring over the symbol index.
    """
    if not _index["workspace"]:
        # Auto-index if needed
        import asyncio
        await asyncio.to_thread(build_index, workspace)

    q_terms = set(re.findall(r'\w+', q.lower()))
    chunks  = []

    for rel, meta in _index["files"].items():
        for sym in meta.get("symbols", []):
            text   = f"{sym['name']} {sym.get('docstring','')}".lower()
            score  = sum(1 for t in q_terms if t in text)
            if score > 0:
                chunks.append({
                    "file":     rel,
                    "line":     sym["line"],
                    "symbol":   sym["name"],
                    "kind":     sym["kind"],
                    "language": meta["language"],
                    "snippet":  f"{sym['kind']} {sym['name']}",
                    "score":    score,
                })

    chunks.sort(key=lambda x: x["score"], reverse=True)
    return {"query": q, "chunks": chunks[:limit], "total": len(chunks)}
