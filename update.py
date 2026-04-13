"""
update.py — Incremental ingestion pipeline.

This is the main entry point for populating the AI memory store.
Run it on your laptop whenever you have new data.

Pipeline:
  1. Scan all configured directories for files
  2. Hash each file to detect changes (skip unchanged files)
  3. Parse files into documents via the ingestion router
  4. Clean and normalize text
  5. Chunk text into ~300-word segments
  6. Hash each chunk to deduplicate against existing DB
  7. Batch-encode new chunks via SentenceTransformer
  8. Insert into SQLite + FAISS
  9. Single FAISS write at end of pipeline
  10. Optional IVF rebuild if threshold crossed

Safe to run repeatedly — fully idempotent via hash-based deduplication.
"""

import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    BATCH_SIZE,
    CHUNK_MAX_WORDS,
    CHUNK_OVERLAP_WORDS,
    DATA_RAW,
    EMBEDDING_MODEL,
    OBSIDIAN_SCAN_DIRS,
    SKIP_PATTERNS,
)
from database.faiss_db import VectorDB
from database.sqlite_db import MemoryDB
from ingestion import process_file

# Maximum file size to process (skip very large files like raw CSV dumps)
MAX_FILE_SIZE_MB = 15
from processing.chunker import chunk_text
from processing.cleaner import clean_text, compute_hash


def _should_skip(filepath: Path) -> bool:
    """Check if a file path matches any skip pattern."""
    parts = filepath.parts
    for pattern in SKIP_PATTERNS:
        if any(pattern in p for p in parts):
            return True
    return False


def _hash_file(filepath: Path) -> str:
    """Compute SHA-256 of file contents for change detection."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(65536)  # 64 KB chunks
                if not chunk:
                    break
                h.update(chunk)
    except (OSError, PermissionError):
        return ""
    return h.hexdigest()


def _collect_files() -> list:
    """
    Gather all candidate files from data_raw/ and Obsidian scan directories.
    Deduplicates by absolute path.
    """
    seen_paths = set()
    files = []

    # Source 1: data_raw/ (user-dropped exports)
    scan_roots = [DATA_RAW]

    # Source 2: Obsidian vault directories
    for d in OBSIDIAN_SCAN_DIRS:
        if d.exists():
            scan_roots.append(d)

    for root_dir in scan_roots:
        if not root_dir.exists():
            continue
        for filepath in root_dir.rglob("*"):
            if not filepath.is_file():
                continue
            if _should_skip(filepath):
                continue
            # Skip files larger than threshold
            try:
                size_mb = filepath.stat().st_size / (1024 * 1024)
                if size_mb > MAX_FILE_SIZE_MB:
                    continue
            except OSError:
                continue

            abs_path = filepath.resolve()
            if abs_path in seen_paths:
                continue
            seen_paths.add(abs_path)
            files.append(filepath)

    return files


def run_update():
    """Execute the full incremental update pipeline."""
    t_start = time.time()
    print(f"{'=' * 60}", file=sys.stderr)
    print(f"  AI Memory — Incremental Update Pipeline", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)

    # ─────────────────────────────────────────────
    # 1. Collect files
    # ─────────────────────────────────────────────
    files = _collect_files()
    print(f"\n[1/6] Discovered {len(files)} candidate files.", file=sys.stderr)

    if not files:
        print("No files found. Nothing to do.", file=sys.stderr)
        return

    # ─────────────────────────────────────────────
    # 2. Initialize storage
    # ─────────────────────────────────────────────
    db = MemoryDB()
    vec_db = VectorDB()
    existing_hashes = db.get_existing_hashes()
    print(
        f"[2/6] Database loaded: {len(existing_hashes)} existing chunks.",
        file=sys.stderr,
    )

    # ─────────────────────────────────────────────
    # 3. Parse → Clean → Chunk → Deduplicate
    # ─────────────────────────────────────────────
    new_chunks = []
    files_processed = 0
    files_skipped = 0
    docs_parsed = 0

    for file_idx, filepath in enumerate(files, 1):
        # Progress every 50 files
        if file_idx % 50 == 0 or file_idx == 1:
            print(
                f"  Parsing file {file_idx}/{len(files)}: {filepath.name}",
                file=sys.stderr,
            )
        try:
            for document in process_file(filepath):
                docs_parsed += 1
                text = clean_text(document.get("text", ""))
                if not text:
                    continue

                chunks = chunk_text(
                    text,
                    max_words=CHUNK_MAX_WORDS,
                    overlap=CHUNK_OVERLAP_WORDS,
                )

                for chunk_content in chunks:
                    chunk_hash = compute_hash(chunk_content)

                    if chunk_hash in existing_hashes:
                        continue  # Already embedded — skip

                    # Register hash to prevent intra-run duplicates
                    existing_hashes.add(chunk_hash)

                    new_chunks.append(
                        {
                            "hash": chunk_hash,
                            "text": chunk_content,
                            "source": document.get("source", filepath.name),
                            "timestamp": document.get("timestamp", ""),
                            "tags": document.get("tags", ""),
                        }
                    )
            files_processed += 1
        except Exception as e:
            print(
                f"  [WARN] Error processing {filepath.name}: {e}",
                file=sys.stderr,
            )
            files_skipped += 1

    print(
        f"[3/6] Parsed {docs_parsed} documents from {files_processed} files "
        f"({files_skipped} skipped). Found {len(new_chunks)} NEW unique chunks.",
        file=sys.stderr,
    )

    if not new_chunks:
        print(
            "\n✅ System is fully synced — no new data to process.",
            file=sys.stderr,
        )
        db.close()
        return

    # ─────────────────────────────────────────────
    # 4. Lazy-load SentenceTransformer
    # ─────────────────────────────────────────────
    print(f"[4/6] Loading embedding model ({EMBEDDING_MODEL})...", file=sys.stderr)
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)

    # ─────────────────────────────────────────────
    # 5. Batch encode + store
    # ─────────────────────────────────────────────
    total = len(new_chunks)
    print(f"[5/6] Encoding & storing {total} chunks...", file=sys.stderr)

    for batch_start in range(0, total, BATCH_SIZE):
        batch = new_chunks[batch_start : batch_start + BATCH_SIZE]
        texts = [b["text"] for b in batch]

        # Batch encode
        embeddings = model.encode(
            texts,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        # Insert metadata into SQLite (returns mapped IDs)
        mapped_ids = db.insert_memories(batch)

        # Add to FAISS (deferred write)
        vec_db.add_embeddings(embeddings, np.array(mapped_ids))

        progress = min(batch_start + BATCH_SIZE, total)
        print(
            f"  Processed {progress}/{total} chunks...",
            file=sys.stderr,
        )

    # ─────────────────────────────────────────────
    # 6. Finalize: single FAISS write + optional IVF rebuild
    # ─────────────────────────────────────────────
    print(f"[6/6] Saving FAISS index...", file=sys.stderr)
    vec_db.maybe_rebuild_ivf()
    vec_db.save()

    elapsed = time.time() - t_start
    print(
        f"\n{'=' * 60}\n"
        f"  ✅ Update complete!\n"
        f"  New chunks:  {total}\n"
        f"  Total in DB: {db.count()}\n"
        f"  FAISS index: {vec_db.count()} vectors\n"
        f"  Time:        {elapsed:.1f}s\n"
        f"{'=' * 60}",
        file=sys.stderr,
    )

    db.close()


if __name__ == "__main__":
    run_update()
