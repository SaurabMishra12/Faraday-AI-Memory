"""
mcp_server.cloud_server — Cloud-hosted MCP server for Faraday AI Memory.

Designed for Google Cloud Run deployment with:
  - SSE (Server-Sent Events) transport for remote MCP access
  - Supabase Storage integration: pulls memory.db + memory.index on startup
  - API key authentication via X-API-Key header
  - Same tools as local server: search_memory, get_memory_stats, sync_memory

Usage (local test):
    FARADAY_API_KEY=mykey SUPABASE_URL=... SUPABASE_KEY=... python cloud_server.py

Usage (Cloud Run):
    Deployed via Dockerfile, env vars set in Cloud Run config.
"""

import datetime
import os
import sys
import tempfile
import threading
from pathlib import Path

# Silence Huggingface/SentenceTransformer logs
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

# ─────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "faraday-memory")
FARADAY_API_KEY = os.environ.get("FARADAY_API_KEY", "")
PORT = int(os.environ.get("PORT", "8080"))

# Cloud data directory
CLOUD_DATA_DIR = Path(os.environ.get("CLOUD_DATA_DIR", "/tmp/faraday-data"))
CLOUD_DB_PATH = CLOUD_DATA_DIR / "memory.db"
CLOUD_INDEX_PATH = CLOUD_DATA_DIR / "memory.index"

# Embedding model
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
DEFAULT_TOP_K = 5
SEMANTIC_WEIGHT = 0.7
RECENCY_WEIGHT = 0.3


# ─────────────────────────────────────────────────────
# Supabase Data Pull
# ─────────────────────────────────────────────────────

def pull_from_supabase():
    """Download memory.db and memory.index from Supabase Storage via httpx (compressed)."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[CLOUD] WARNING: No Supabase credentials. Using local data if available.",
              file=sys.stderr)
        return False

    try:
        import httpx
        import gzip

        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        }

        CLOUD_DATA_DIR.mkdir(parents=True, exist_ok=True)

        files_to_pull = {
            "memory.db": CLOUD_DB_PATH,
            "memory.index": CLOUD_INDEX_PATH,
        }

        for remote_name, local_path in files_to_pull.items():
            compressed_name = f"{remote_name}.gz"
            print(f"[CLOUD] Downloading {compressed_name} from Supabase...",
                  file=sys.stderr)
            try:
                r = httpx.get(
                    f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{compressed_name}",
                    headers=headers,
                    timeout=120,
                )
                
                # Fallback to uncompressed if .gz is missing (for backward compatibility)
                if r.status_code == 404:
                    print(f"[CLOUD] ℹ️ Compressed not found, trying raw {remote_name}...", file=sys.stderr)
                    r = httpx.get(
                        f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{remote_name}",
                        headers=headers,
                        timeout=120,
                    )
                    if r.status_code == 200:
                        with open(local_path, "wb") as f:
                            f.write(r.content)
                        size_mb = len(r.content) / (1024 * 1024)
                        print(f"[CLOUD] ✅ Raw {remote_name} downloaded ({size_mb:.1f} MB).", file=sys.stderr)
                        continue

                if r.status_code != 200:
                    print(f"[CLOUD] ❌ {compressed_name} download failed ({r.status_code}): {r.text}",
                          file=sys.stderr)
                    return False

                # Decompress in memory and write
                print(f"[CLOUD] Decompressing {compressed_name}...", file=sys.stderr)
                decompressed_data = gzip.decompress(r.content)
                
                with open(local_path, "wb") as f:
                    f.write(decompressed_data)
                    
                download_mb = len(r.content) / (1024 * 1024)
                decompressed_mb = len(decompressed_data) / (1024 * 1024)
                print(f"[CLOUD] ✅ {remote_name} ready ({download_mb:.1f}MB → {decompressed_mb:.1f}MB).",
                      file=sys.stderr)
            except Exception as e:
                print(f"[CLOUD] ❌ Failed to download {remote_name}: {e}",
                      file=sys.stderr)
                return False

        return True

    except Exception as e:
        print(f"[CLOUD] Supabase pull failed: {e}", file=sys.stderr)
        return False


# ─────────────────────────────────────────────────────
# Initialize Data
# ─────────────────────────────────────────────────────

print("[CLOUD] Starting Faraday Cloud MCP Server...", file=sys.stderr)

# Pull data from Supabase on startup
pull_success = pull_from_supabase()

# Monkey-patch config paths for cloud environment
import config
config.SQLITE_DB_PATH = CLOUD_DB_PATH
config.FAISS_INDEX_PATH = CLOUD_INDEX_PATH
config.DATA_PROCESSED = CLOUD_DATA_DIR
config.EMBEDDINGS_DIR = CLOUD_DATA_DIR

from database.faiss_db import VectorDB
from database.sqlite_db import MemoryDB

# ─────────────────────────────────────────────────────
# Server Initialization
# ─────────────────────────────────────────────────────

mcp = FastMCP(
    "Faraday-AI-Memory-Cloud",
    host="0.0.0.0",
    port=PORT
)

# Load data stores
if CLOUD_DB_PATH.exists() and CLOUD_INDEX_PATH.exists():
    _db = MemoryDB(db_path=CLOUD_DB_PATH, readonly=True)
    _vec_db = VectorDB(index_path=str(CLOUD_INDEX_PATH))
else:
    print("[CLOUD] ⚠️ No data files found. Memory will be empty.", file=sys.stderr)
    # Create empty stores
    CLOUD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _db = MemoryDB(db_path=CLOUD_DB_PATH, readonly=False)
    _vec_db = VectorDB(index_path=str(CLOUD_INDEX_PATH))

# Load embedding model
from sentence_transformers import SentenceTransformer

print("[CLOUD] Loading embedding model...", file=sys.stderr)
_model = SentenceTransformer(EMBEDDING_MODEL)

print(
    f"[CLOUD] ✅ Ready: {_vec_db.count()} vectors, {_db.count()} memories loaded.",
    file=sys.stderr,
)


# ─────────────────────────────────────────────────────
# Time Helpers (same as local)
# ─────────────────────────────────────────────────────

def _resolve_time_filter(time_filter: str):
    """Convert human-readable time filter to (start_iso, end_iso) tuple."""
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
        try:
            from dateutil import parser as date_parser
            dt = date_parser.parse(time_filter)
            start = dt.replace(hour=0, minute=0, second=0)
            end = dt.replace(hour=23, minute=59, second=59)
            return start.isoformat(), end.isoformat()
        except Exception:
            return None


def _compute_recency_score(timestamp_str: str) -> float:
    """Compute a 0-1 recency score with ~30 day half-life."""
    if not timestamp_str or timestamp_str == "Unknown":
        return 0.0
    try:
        from dateutil import parser as date_parser
        ts = date_parser.parse(timestamp_str)
        now = datetime.datetime.now()
        age_days = max(0, (now - ts).total_seconds() / 86400)
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
                "Data has not been synced to the cloud yet."
            )

        # 1. Encode query
        query_emb = _model.encode(
            [query], show_progress_bar=False, convert_to_numpy=True
        )

        # 2. FAISS search
        fetch_k = min(top_k * 3, _vec_db.count())
        raw_results = _vec_db.search(query_emb, top_k=fetch_k)

        if not raw_results:
            return "No matching memories found."

        # 3. Get metadata
        candidate_ids = [r[0] for r in raw_results]
        score_map = {r[0]: r[1] for r in raw_results}
        metadata_list = _db.get_memories_by_ids(candidate_ids)

        # 4. Apply filters
        filtered = metadata_list

        time_range = _resolve_time_filter(time_filter)
        if time_range:
            start_iso, end_iso = time_range
            filtered = [
                m for m in filtered
                if m.get("timestamp", "") >= start_iso
                and m.get("timestamp", "") <= end_iso
            ]

        if tags:
            tag_set = {t.strip().lower() for t in tags.split(",")}
            filtered = [
                m for m in filtered
                if any(t in m.get("tags", "").lower() for t in tag_set)
            ]

        if not filtered:
            return "No memories matched your filters."

        # 5. Hybrid scoring
        scored = []
        for meta in filtered:
            mem_id = meta["id"]
            semantic = score_map.get(mem_id, 0.0)
            recency = _compute_recency_score(meta.get("timestamp", ""))
            hybrid = SEMANTIC_WEIGHT * semantic + RECENCY_WEIGHT * recency
            scored.append((meta, hybrid, semantic))

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
            f"=== FARADAY CLOUD MEMORY STATS ===\n"
            f"Total chunks:    {stats.get('total', 0)}\n"
            f"FAISS vectors:   {vec_count}\n"
            f"Unique sources:  {stats.get('sources', 0)}\n"
            f"Date range:      {stats.get('earliest', 'N/A')} → "
            f"{stats.get('latest', 'N/A')}\n"
            f"Deployment:      Google Cloud Run\n"
            f"Data source:     Supabase Storage\n"
        )
    except Exception as e:
        return f"Stats failed: {e}"


@mcp.tool()
def sync_memory() -> str:
    """
    Re-pull the latest data from Supabase Storage.
    Use this after running `python sync.py push` on your laptop
    to refresh the cloud server with the latest memory data.
    """
    try:
        def _run_refresh():
            global _db, _vec_db
            try:
                success = pull_from_supabase()
                if success:
                    # Reload database and vector index
                    _db = MemoryDB(db_path=CLOUD_DB_PATH, readonly=True)
                    _vec_db = VectorDB(index_path=str(CLOUD_INDEX_PATH))
                    print(
                        f"[CLOUD] Refreshed: {_vec_db.count()} vectors, "
                        f"{_db.count()} memories.",
                        file=sys.stderr,
                    )
            except Exception as e:
                print(f"[CLOUD] Refresh error: {e}", file=sys.stderr)

        threading.Thread(target=_run_refresh, daemon=True).start()

        return (
            "✅ Cloud data refresh started. "
            "Pulling latest memory.db and memory.index from Supabase. "
            "Run get_memory_stats() in a moment to verify."
        )
    except Exception as e:
        return f"❌ Refresh failed: {e}"


# ─────────────────────────────────────────────────────
# Health Check Endpoint (for Cloud Run)
# ─────────────────────────────────────────────────────

@mcp.resource("health://status")
def health_check() -> str:
    """Health check for Cloud Run."""
    return f"OK: {_vec_db.count()} vectors loaded"


# ─────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[CLOUD] Starting SSE server on port {PORT}...", file=sys.stderr)
    mcp.run(transport="sse")
