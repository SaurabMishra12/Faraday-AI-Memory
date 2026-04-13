"""
database.sqlite_db — Production SQLite metadata store with FTS5 full-text search.

Features:
  - WAL journal mode for concurrent read/write
  - FTS5 virtual table for keyword search
  - Hash-based deduplication (UNIQUE constraint on hash column)
  - Time-range queries via indexed timestamp column
  - Tag filtering
  - Batch insert via executemany
  - Preserves ordered retrieval by maintaining original ID sequence
"""

import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

# Import from root config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SQLITE_DB_PATH


class MemoryDB:
    """
    SQLite-backed metadata store for memory chunks.
    Each chunk gets a monotonically increasing integer ID that maps
    exactly to its FAISS vector index position.
    """

    def __init__(self, db_path: Optional[Path] = None, readonly: bool = False):
        path = str(db_path or SQLITE_DB_PATH)
        if readonly:
            # Read-only URI connection — safe for concurrent MCP server reads
            uri = f"file:{path}?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            self.conn = sqlite3.connect(path, check_same_thread=False)
            # WAL mode: allows concurrent readers while writing
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")

        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        """Create core tables and FTS5 index if they don't exist."""
        with self.conn:
            # Core metadata table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    hash      TEXT    UNIQUE NOT NULL,
                    text      TEXT    NOT NULL,
                    source    TEXT    NOT NULL DEFAULT '',
                    timestamp TEXT    NOT NULL DEFAULT '',
                    tags      TEXT    NOT NULL DEFAULT '',
                    created   TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # Indices for fast lookups
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hash ON memories(hash);"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON memories(timestamp);"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tags ON memories(tags);"
            )

            # FTS5 virtual table for full-text keyword search
            # content= makes it an external-content FTS table (no data duplication)
            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(text, source, tags, content=memories, content_rowid=id)
            """)

            # Triggers to keep FTS5 in sync with the main table
            self.conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, text, source, tags)
                    VALUES (new.id, new.text, new.source, new.tags);
                END;

                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, text, source, tags)
                    VALUES ('delete', old.id, old.text, old.source, old.tags);
                END;

                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, text, source, tags)
                    VALUES ('delete', old.id, old.text, old.source, old.tags);
                    INSERT INTO memories_fts(rowid, text, source, tags)
                    VALUES (new.id, new.text, new.source, new.tags);
                END;
            """)

    # ─────────────────────────────────────────────
    # Deduplication
    # ─────────────────────────────────────────────

    def get_existing_hashes(self) -> Set[str]:
        """
        Fetch all known content hashes.
        Used by update.py to skip already-processed chunks.
        """
        cur = self.conn.execute("SELECT hash FROM memories")
        return {row["hash"] for row in cur.fetchall()}

    # ─────────────────────────────────────────────
    # Batch Insert
    # ─────────────────────────────────────────────

    def insert_memories(self, data: List[Dict]) -> List[int]:
        """
        Insert a batch of chunks. Returns list of SQLite row IDs
        that map exactly to FAISS vector positions.

        Uses INSERT OR IGNORE to safely skip duplicates within
        the same batch.
        """
        ids: List[int] = []
        with self.conn:
            for item in data:
                cur = self.conn.execute(
                    """
                    INSERT OR IGNORE INTO memories (hash, text, source, timestamp, tags)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        item.get("hash", ""),
                        item.get("text", ""),
                        item.get("source", ""),
                        item.get("timestamp", ""),
                        item.get("tags", ""),
                    ),
                )

                if cur.lastrowid and cur.rowcount > 0:
                    ids.append(cur.lastrowid)
                else:
                    # Retrieve existing ID for this hash (it was a duplicate)
                    existing = self.conn.execute(
                        "SELECT id FROM memories WHERE hash=?",
                        (item["hash"],),
                    ).fetchone()
                    if existing:
                        ids.append(existing["id"])

        return ids

    # ─────────────────────────────────────────────
    # Retrieval
    # ─────────────────────────────────────────────

    def get_memories_by_ids(self, ids: List[int]) -> List[Dict]:
        """
        Retrieve full metadata for a list of FAISS-matched IDs.
        Returns results in the SAME ORDER as the input IDs.
        """
        if not ids:
            return []

        placeholders = ",".join(["?"] * len(ids))
        query = f"SELECT * FROM memories WHERE id IN ({placeholders})"
        cur = self.conn.execute(query, ids)

        row_dict = {row["id"]: dict(row) for row in cur.fetchall()}
        return [row_dict[i] for i in ids if i in row_dict]

    def search_by_time_range(
        self, start_iso: str, end_iso: str, limit: int = 100
    ) -> List[Dict]:
        """
        Retrieve memories within a time range (ISO 8601 strings).
        """
        cur = self.conn.execute(
            """
            SELECT id FROM memories
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (start_iso, end_iso, limit),
        )
        return [row["id"] for row in cur.fetchall()]

    def search_by_tags(self, tag: str, limit: int = 100) -> List[int]:
        """Return IDs of memories matching a tag substring."""
        cur = self.conn.execute(
            "SELECT id FROM memories WHERE tags LIKE ? LIMIT ?",
            (f"%{tag}%", limit),
        )
        return [row["id"] for row in cur.fetchall()]

    def keyword_search(self, query: str, limit: int = 20) -> List[int]:
        """
        Full-text keyword search via FTS5.
        Returns matching memory IDs ranked by BM25 relevance.
        """
        try:
            cur = self.conn.execute(
                """
                SELECT rowid FROM memories_fts
                WHERE memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )
            return [row["rowid"] for row in cur.fetchall()]
        except Exception:
            # FTS match syntax can fail on certain special characters
            return []

    # ─────────────────────────────────────────────
    # Stats
    # ─────────────────────────────────────────────

    def count(self) -> int:
        """Total number of stored memory chunks."""
        return self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def get_stats(self) -> Dict:
        """Return diagnostic statistics."""
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) as total,
                MIN(timestamp) as earliest,
                MAX(timestamp) as latest,
                COUNT(DISTINCT source) as sources
            FROM memories
            """
        ).fetchone()
        return dict(row) if row else {}

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────

    def close(self):
        """Close the database connection."""
        self.conn.close()
