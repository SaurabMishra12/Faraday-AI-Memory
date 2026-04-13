"""
config.py — Central configuration for the AI Memory MCP system.

All paths, model settings, and tuning constants live here.
Every module imports from this file; nothing is hardcoded elsewhere.
"""

import os
from pathlib import Path

# ─────────────────────────────────────────────────────
# Directory Layout
# ─────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.resolve()

# Where raw exports / documents are dropped for ingestion
DATA_RAW = BASE_DIR / "data_raw"

# Processed artefacts (SQLite DB, FAISS index)
DATA_PROCESSED = BASE_DIR / "data_processed"

# FAISS index file
EMBEDDINGS_DIR = BASE_DIR / "embeddings"

# Obsidian vault root (parent of ai-memory-mcp/)
OBSIDIAN_VAULT = BASE_DIR.parent

# Obsidian source directories to scan during update
OBSIDIAN_SCAN_DIRS = [
    OBSIDIAN_VAULT / "00 - Inbox",
    OBSIDIAN_VAULT / "01 - Raw Sources",
    OBSIDIAN_VAULT / "02 - Wiki",
    OBSIDIAN_VAULT / "03 - Data Lake",
]

# Directories / patterns to skip during recursive scanning
SKIP_PATTERNS = [
    ".qdrant", ".chroma", ".venv", "__pycache__",
    "faraday-server", "ai-memory-mcp", "node_modules",
    ".git", ".obsidian",
]

# Ensure critical dirs exist
for _d in [DATA_RAW, DATA_PROCESSED, EMBEDDINGS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────
# Database Paths
# ─────────────────────────────────────────────────────

SQLITE_DB_PATH = DATA_PROCESSED / "memory.db"
FAISS_INDEX_PATH = EMBEDDINGS_DIR / "memory.index"

# ─────────────────────────────────────────────────────
# Embedding Model
# ─────────────────────────────────────────────────────

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384       # Output dimension for all-MiniLM-L6-v2
BATCH_SIZE = 64            # SentenceTransformer encode batch size

# ─────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────

CHUNK_MAX_WORDS = 300      # Target words per chunk
CHUNK_OVERLAP_WORDS = 50   # Overlap between adjacent chunks
CHUNK_MIN_LENGTH = 30      # Minimum characters — skip trivially short chunks

# ─────────────────────────────────────────────────────
# Search / Scoring
# ─────────────────────────────────────────────────────

SEMANTIC_WEIGHT = 0.7      # Weight for vector similarity in hybrid score
RECENCY_WEIGHT = 0.3       # Weight for timestamp recency in hybrid score
DEFAULT_TOP_K = 5          # Default number of results

# ─────────────────────────────────────────────────────
# FAISS Tuning
# ─────────────────────────────────────────────────────

# When total vectors exceed this threshold, rebuild as IVFFlat
# Below this, IndexFlatIP is fine (brute-force is fast enough)
FAISS_IVF_THRESHOLD = 10_000
FAISS_NLIST = 100          # Number of Voronoi cells for IVFFlat
FAISS_NPROBE = 10          # Cells to search at query time (speed/accuracy tradeoff)

# ─────────────────────────────────────────────────────
# OCR (optional)
# ─────────────────────────────────────────────────────

OCR_ENABLED = True         # Set False to skip image ingestion entirely
# If tesseract is not in PATH, set the full path here:
# e.g. r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_CMD = None

# ─────────────────────────────────────────────────────
# Cloud Sync (optional — Supabase)
# ─────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "faraday-memory")

# ─────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
