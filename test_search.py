"""Quick smoke test for the search pipeline."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'

import logging
logging.getLogger('sentence_transformers').setLevel(logging.ERROR)
logging.getLogger('transformers').setLevel(logging.ERROR)

from config import EMBEDDING_MODEL
from database.faiss_db import VectorDB
from database.sqlite_db import MemoryDB
from sentence_transformers import SentenceTransformer
import time

db = MemoryDB(readonly=True)
vec_db = VectorDB()
model = SentenceTransformer(EMBEDDING_MODEL)

print(f"DB: {db.count()} rows | FAISS: {vec_db.count()} vectors")

# Test search with timing
query = "What projects is Saurab working on?"
t0 = time.perf_counter()
query_emb = model.encode([query], show_progress_bar=False, convert_to_numpy=True)
t_encode = time.perf_counter() - t0

t0 = time.perf_counter()
results = vec_db.search(query_emb, top_k=3)
t_search = time.perf_counter() - t0

print(f"\nQuery: '{query}'")
print(f"Encode: {t_encode*1000:.1f}ms | Search: {t_search*1000:.1f}ms")
print(f"Results: {len(results)}")

ids = [r[0] for r in results]
metas = db.get_memories_by_ids(ids)
for i, m in enumerate(metas):
    score = results[i][1]
    source = m.get("source", "?")
    text_preview = m.get("text", "")[:120].replace("\n", " ")
    print(f"  [{i+1}] Score={score:.3f} | {source}")
    print(f"      {text_preview}...")

# Stats
stats = db.get_stats()
print(f"\nStats: {stats}")
db.close()
print("\nAll tests passed!")
