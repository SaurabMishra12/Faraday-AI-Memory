"""
database.faiss_db — Production FAISS vector index with adaptive indexing.

Key design decisions:
  - Uses IndexFlatIP (inner product on L2-normalized vectors) for small datasets.
  - Automatically trains and rebuilds as IVFFlat when vectors exceed threshold
    (default 10K), giving O(√N) search instead of O(N).
  - Deferred disk writes: caller must explicitly call save() — eliminates
    the O(N²) disk I/O from writing after every batch.
  - IndexIDMap wrapper maps FAISS positions to SQLite row IDs.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import faiss
import numpy as np

# Import from root config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    EMBEDDING_DIM,
    FAISS_INDEX_PATH,
    FAISS_IVF_THRESHOLD,
    FAISS_NLIST,
    FAISS_NPROBE,
)


class VectorDB:
    """
    FAISS-backed vector index with adaptive index type selection.

    For < FAISS_IVF_THRESHOLD vectors: brute-force IndexFlatIP.
    For >= threshold: IVFFlat with configurable nlist/nprobe.
    """

    def __init__(
        self,
        dim: int = EMBEDDING_DIM,
        index_path: Optional[str] = None,
    ):
        self.dim = dim
        self.index_path = index_path or str(FAISS_INDEX_PATH)
        self.index: Optional[faiss.Index] = None
        self._load_or_create()

    def _load_or_create(self):
        """Load existing index from disk or create a fresh one."""
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
            print(
                f"[VectorDB] Loaded FAISS index: {self.index.ntotal} vectors",
                file=sys.stderr,
            )
        else:
            print("[VectorDB] Creating new FAISS IndexFlatIP.", file=sys.stderr)
            base = faiss.IndexFlatIP(self.dim)
            self.index = faiss.IndexIDMap(base)

    def add_embeddings(self, embeddings: np.ndarray, ids: np.ndarray):
        """
        Add a batch of embeddings with their corresponding SQLite IDs.

        Args:
            embeddings: (N, dim) float32 array — MUST be L2-normalized.
            ids:        (N,) int64 array of SQLite row IDs.

        NOTE: Does NOT write to disk. Call save() explicitly when done.
        """
        if embeddings.shape[0] == 0:
            return

        assert embeddings.shape[1] == self.dim, (
            f"Dimension mismatch: got {embeddings.shape[1]}, expected {self.dim}"
        )

        embeddings = embeddings.astype(np.float32)
        ids = ids.astype(np.int64)

        # L2-normalize for cosine similarity via inner product
        faiss.normalize_L2(embeddings)

        self.index.add_with_ids(embeddings, ids)

    def search(
        self, query_embedding: np.ndarray, top_k: int = 5
    ) -> List[Tuple[int, float]]:
        """
        Find the top_k most similar vectors.

        Args:
            query_embedding: (1, dim) or (dim,) float32 array.
            top_k: Number of results.

        Returns:
            List of (sqlite_id, similarity_score) tuples.
            Score is cosine similarity (higher = better, range 0-1).
        """
        if self.index is None or self.index.ntotal == 0:
            return []

        query_embedding = query_embedding.astype(np.float32)
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        # Normalize query for cosine similarity
        faiss.normalize_L2(query_embedding)

        # Set nprobe for IVF indices (no-op for flat indices)
        try:
            # Access the underlying IVF quantizer if it exists
            ivf = faiss.extract_index_ivf(self.index)
            if ivf is not None:
                ivf.nprobe = FAISS_NPROBE
        except Exception:
            pass

        distances, indices = self.index.search(query_embedding, top_k)

        results = []
        for i in range(len(indices[0])):
            idx = int(indices[0][i])
            score = float(distances[0][i])
            if idx != -1:  # FAISS returns -1 for missing matches
                results.append((idx, score))

        return results

    def maybe_rebuild_ivf(self):
        """
        If total vectors exceed the IVF threshold, rebuild as IVFFlat
        for O(√N) search performance. Called after a full update cycle.

        This is an expensive operation (re-indexes everything) but only
        happens once when crossing the threshold.
        """
        if self.index.ntotal < FAISS_IVF_THRESHOLD:
            return

        # Check if already IVF
        try:
            ivf = faiss.extract_index_ivf(self.index)
            if ivf is not None:
                return  # Already IVF, no rebuild needed
        except Exception:
            pass

        print(
            f"[VectorDB] Rebuilding as IVFFlat ({self.index.ntotal} vectors, "
            f"nlist={FAISS_NLIST})...",
            file=sys.stderr,
        )

        n = self.index.ntotal

        try:
            # IndexIDMap stores vectors in the sub-index and IDs in id_map
            # Access the underlying flat index vectors directly
            sub_index = self.index.index
            all_vectors = faiss.vector_to_array(sub_index.xb).reshape(n, self.dim).copy()

            # Extract the ID mapping
            all_ids = faiss.vector_to_array(self.index.id_map).copy()

            # Build new IVFFlat index
            quantizer = faiss.IndexFlatIP(self.dim)
            ivf_index = faiss.IndexIVFFlat(
                quantizer, self.dim, FAISS_NLIST, faiss.METRIC_INNER_PRODUCT
            )

            # Train on existing vectors
            ivf_index.train(all_vectors)

            # Wrap in IDMap and add with original IDs
            new_index = faiss.IndexIDMap(ivf_index)
            new_index.add_with_ids(all_vectors, all_ids)

            self.index = new_index
            print(f"[VectorDB] IVFFlat rebuild complete.", file=sys.stderr)

        except Exception as e:
            print(
                f"[VectorDB] IVF rebuild failed: {e}. Keeping flat index.",
                file=sys.stderr,
            )

    def save(self):
        """Persist the index to disk. Call once at end of update pipeline."""
        if self.index is not None:
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
            faiss.write_index(self.index, self.index_path)
            print(
                f"[VectorDB] Saved index ({self.index.ntotal} vectors) to {self.index_path}",
                file=sys.stderr,
            )

    def count(self) -> int:
        """Total number of indexed vectors."""
        return self.index.ntotal if self.index else 0
