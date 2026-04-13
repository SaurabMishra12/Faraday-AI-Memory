"""
mcp_server.main — Production MCP server for Personal AI Memory.

Exposes three tools via the Model Context Protocol (stdio transport):
  1. search_memory   — Hybrid semantic + recency search
  2. get_memory_stats — Diagnostic info about the memory store
  3. sync_memory     — Trigger background ingestion

Design:
  - Model, FAISS index, and SQLite are loaded ONCE at startup
  - Queries run in <100ms (encode + FAISS search + SQLite lookup)
  - No writes during search — fully non-blocking for concurrent reads
  - Hybrid scoring: α × semantic_similarity + (1-α) × recency_score
"""

import datetime
import os
import sys
import threading
from pathlib import Path

# Silence Huggingface/SentenceTransformer logs that break JSON-RPC stdio
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import logging

logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)

# Fix imports: add project root to path
PROJECT_ROOT = str(Path(__file__).parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP

from config import (
    DEFAULT_TOP_K,
    EMBEDDING_MODEL,
    RECENCY_WEIGHT,
    SEMANTIC_WEIGHT,
)
from database.faiss_db import VectorDB
from database.sqlite_db import MemoryDB

# ─────────────────────────────────────────────────────
# Server Initialization
# ─────────────────────────────────────────────────────

mcp = FastMCP("Faraday-AI-Memory")

# Eager load: everything initialized once at startup
print("Loading AI Memory services...", file=sys.stderr)

_db = MemoryDB(readonly=True)
_vec_db = VectorDB()

from sentence_transformers import SentenceTransformer

_model = SentenceTransformer(EMBEDDING_MODEL)

print(
    f"Ready: {_vec_db.count()} vectors, {_db.count()} memories loaded.",
    file=sys.stderr,
)


# ─────────────────────────────────────────────────────
# Time Filter Helpers
# ─────────────────────────────────────────────────────

def _resolve_time_filter(time_filter: str):
    """
    Convert human-readable time filter to (start_iso, end_iso) tuple.
    Supports: "today", "yesterday", "last_week", "last_month",
    or an ISO date string like "2026-04-10".
    Returns None if no filter.
    """
    if not time_filter or time_filter.lower() == "none":
        return None

    now = datetime.datetime.now()
    key = time_filter.lower().strip()

    if key == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.isoformat(), now.isoformat()
    elif key == "yesterday":
        yesterday = now - datetime.timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = yesterday.replace(hour=23, minute=59, second=59)
        return start.isoformat(), end.isoformat()
    elif key in ("last_week", "this_week", "week"):
        start = now - datetime.timedelta(days=7)
        return start.isoformat(), now.isoformat()
    elif key in ("last_month", "this_month", "month"):
        start = now - datetime.timedelta(days=30)
        return start.isoformat(), now.isoformat()
    else:
        # Try parsing as ISO date
        try:
            from dateutil import parser as date_parser

            dt = date_parser.parse(time_filter)
            start = dt.replace(hour=0, minute=0, second=0)
            end = dt.replace(hour=23, minute=59, second=59)
            return start.isoformat(), end.isoformat()
        except Exception:
            return None


def _compute_recency_score(timestamp_str: str) -> float:
    """
    Compute a 0-1 recency score.
    Recent items score higher. Uses exponential decay with ~30 day half-life.
    """
    if not timestamp_str or timestamp_str == "Unknown":
        return 0.0

    try:
        from dateutil import parser as date_parser

        ts = date_parser.parse(timestamp_str)
        now = datetime.datetime.now()
        age_days = max(0, (now - ts).total_seconds() / 86400)
        # Exponential decay: half-life of 30 days
        return 2.0 ** (-age_days / 30.0)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────


@mcp.tool()
def search_memory(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    time_filter: str = "",
    tags: str = "",
) -> str:
    """
    Search Saurab's personal AI memory (past chats, documents, notes, research).

    Use this tool whenever you need context about Saurab's history,
    past actions, architecture decisions, projects, or personal knowledge.

    Args:
        query:       Semantic search string (e.g. 'sparse communication paper')
        top_k:       Maximum results to return (default 5)
        time_filter: Optional time constraint: 'today', 'yesterday',
                     'last_week', 'last_month', or an ISO date like '2026-04-10'
        tags:        Optional comma-separated tag filter (e.g. 'chatgpt,research')
    """
    try:
        if _vec_db.count() == 0:
            return (
                "Memory store is empty. "
                "Run `python update.py` to synchronize your data."
            )

        # 1. Encode query (single vector, ~5ms on CPU)
        query_emb = _model.encode(
            [query], show_progress_bar=False, convert_to_numpy=True
        )

        # 2. FAISS search — get candidate IDs with semantic scores
        # Fetch extra candidates for re-ranking
        fetch_k = min(top_k * 3, _vec_db.count())
        raw_results = _vec_db.search(query_emb, top_k=fetch_k)

        if not raw_results:
            return "No matching memories found."

        # 3. Get metadata for all candidates
        candidate_ids = [r[0] for r in raw_results]
        score_map = {r[0]: r[1] for r in raw_results}
        metadata_list = _db.get_memories_by_ids(candidate_ids)

        # 4. Apply filters
        filtered = metadata_list

        # Time filter
        time_range = _resolve_time_filter(time_filter)
        if time_range:
            start_iso, end_iso = time_range
            filtered = [
                m
                for m in filtered
                if m.get("timestamp", "") >= start_iso
                and m.get("timestamp", "") <= end_iso
            ]

        # Tag filter
        if tags:
            tag_set = {t.strip().lower() for t in tags.split(",")}
            filtered = [
                m
                for m in filtered
                if any(
                    t in m.get("tags", "").lower() for t in tag_set
                )
            ]

        if not filtered:
            return "No memories matched your filters."

        # 5. Hybrid scoring: semantic + recency
        scored = []
        for meta in filtered:
            mem_id = meta["id"]
            semantic = score_map.get(mem_id, 0.0)
            recency = _compute_recency_score(meta.get("timestamp", ""))
            hybrid = SEMANTIC_WEIGHT * semantic + RECENCY_WEIGHT * recency
            scored.append((meta, hybrid, semantic))

        # Sort by hybrid score (descending)
        scored.sort(key=lambda x: x[1], reverse=True)

        # 6. Format output
        results = scored[:top_k]
        output_lines = [f"=== FARADAY MEMORY ({len(results)} results) ===\n"]

        for i, (meta, hybrid, semantic) in enumerate(results, 1):
            output_lines.append(
                f"--- Result {i} [Score: {hybrid:.3f}] ---\n"
                f"Source:    {meta.get('source', 'Unknown')}\n"
                f"Date:      {meta.get('timestamp', 'Unknown')}\n"
                f"Tags:      {meta.get('tags', '')}\n"
                f"Semantic:  {semantic:.3f}  |  Recency: "
                f"{_compute_recency_score(meta.get('timestamp', '')):.3f}\n"
                f"Content:\n{meta.get('text', '')}\n"
            )

        return "\n".join(output_lines)

    except Exception as e:
        import traceback

        return f"Memory search failed: {e}\n{traceback.format_exc()}"


@mcp.tool()
def get_memory_stats() -> str:
    """
    Get diagnostic statistics about the AI memory store.
    Shows total chunks, vector count, date range, and source count.
    """
    try:
        stats = _db.get_stats()
        vec_count = _vec_db.count()

        return (
            f"=== FARADAY MEMORY STATS ===\n"
            f"Total chunks:    {stats.get('total', 0)}\n"
            f"FAISS vectors:   {vec_count}\n"
            f"Unique sources:  {stats.get('sources', 0)}\n"
            f"Date range:      {stats.get('earliest', 'N/A')} → "
            f"{stats.get('latest', 'N/A')}\n"
        )
    except Exception as e:
        return f"Stats failed: {e}"


@mcp.tool()
def sync_memory() -> str:
    """
    Trigger an incremental memory sync in the background.
    This scans all data directories, processes new documents,
    and updates the FAISS index. Safe to call repeatedly.
    """
    try:

        def _run_update():
            try:
                import subprocess

                subprocess.run(
                    [sys.executable, str(Path(PROJECT_ROOT) / "update.py")],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                )
            except Exception as e:
                print(f"Background sync error: {e}", file=sys.stderr)

        threading.Thread(target=_run_update, daemon=True).start()

        return (
            "✅ Memory sync started in background. "
            "New data will be available after processing completes. "
            "Run get_memory_stats() to verify."
        )
    except Exception as e:
        return f"❌ Sync failed to start: {e}"


# ─────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
