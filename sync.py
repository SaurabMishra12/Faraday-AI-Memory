"""
sync.py — Cloud sync for Faraday AI Memory.

Pushes the local SQLite database and FAISS index to Supabase Storage,
enabling the cloud-hosted MCP server on Cloud Run to serve queries
from the same data.

Uses httpx directly (no heavy Supabase SDK) for maximum compatibility.

Usage:
    python sync.py push    # Upload local DB + index to cloud
    python sync.py pull    # Download cloud DB + index to local
    python sync.py status  # Check what's in the cloud bucket

Requires SUPABASE_URL and SUPABASE_KEY in config.py or env vars.
"""

import os
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from config import (
    FAISS_INDEX_PATH,
    SQLITE_DB_PATH,
    SUPABASE_BUCKET,
    SUPABASE_KEY,
    SUPABASE_URL,
)


def _check_credentials():
    """Validate Supabase credentials are available."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(
            "❌ Error: Supabase credentials not configured.\n"
            "Set SUPABASE_URL and SUPABASE_KEY in config.py or environment.\n"
            "\n"
            "Your Supabase project URL looks like:\n"
            "  https://qwxagrmoryojholseclm.supabase.co\n"
            "\n"
            "Get your anon key from:\n"
            "  Supabase Dashboard → Settings → API → anon public key",
            file=sys.stderr,
        )
        sys.exit(1)


def _headers():
    """Common headers for Supabase Storage API."""
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }


def _ensure_bucket():
    """Create the storage bucket if it doesn't exist."""
    import httpx

    # Check if bucket exists
    r = httpx.get(
        f"{SUPABASE_URL}/storage/v1/bucket/{SUPABASE_BUCKET}",
        headers=_headers(),
        timeout=30,
    )

    if r.status_code == 200:
        print(f"  Bucket '{SUPABASE_BUCKET}' exists.", file=sys.stderr)
        return True

    # Create bucket
    print(f"  Creating bucket '{SUPABASE_BUCKET}'...", file=sys.stderr)
    r = httpx.post(
        f"{SUPABASE_URL}/storage/v1/bucket",
        headers={**_headers(), "Content-Type": "application/json"},
        json={
            "id": SUPABASE_BUCKET,
            "name": SUPABASE_BUCKET,
            "public": False,
            "file_size_limit": 200 * 1024 * 1024,  # 200 MB
        },
        timeout=30,
    )

    if r.status_code in (200, 201):
        print(f"  ✅ Bucket created.", file=sys.stderr)
        return True
    else:
        print(
            f"  ⚠️ Bucket creation response ({r.status_code}): {r.text}",
            file=sys.stderr,
        )
        # May already exist, try anyway
        return True


def push():
    """Upload local database and FAISS index (compressed) to Supabase Storage."""
    import httpx
    import gzip

    _check_credentials()
    _ensure_bucket()

    files_to_upload = {
        "memory.db": SQLITE_DB_PATH,
        "memory.index": FAISS_INDEX_PATH,
    }

    for remote_name, local_path in files_to_upload.items():
        path = Path(local_path)
        if not path.exists():
            print(f"  [SKIP] {remote_name} — local file not found at {path}",
                  file=sys.stderr)
            continue

        raw_size_mb = path.stat().st_size / (1024 * 1024)
        
        # We always compress before uploading
        compressed_name = f"{remote_name}.gz"
        print(f"  Compressing {remote_name} ({raw_size_mb:.1f} MB)...", file=sys.stderr)
        
        with open(path, "rb") as f_in:
            file_content = gzip.compress(f_in.read())
            
        comp_size_mb = len(file_content) / (1024 * 1024)
        print(f"  Uploading {compressed_name} ({comp_size_mb:.1f} MB)...", file=sys.stderr)

        # Try to remove existing file first (upsert)
        httpx.delete(
            f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{compressed_name}",
            headers=_headers(),
            timeout=30,
        )

        # Upload compressed file
        r = httpx.post(
            f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{compressed_name}",
            headers={
                **_headers(),
                "Content-Type": "application/gzip",
                "x-upsert": "true",
            },
            content=file_content,
            timeout=120,
        )

        if r.status_code in (200, 201):
            print(f"  ✅ {compressed_name} uploaded successfully.", file=sys.stderr)
        else:
            print(
                f"  ❌ {compressed_name} upload failed ({r.status_code}): {r.text}",
                file=sys.stderr,
            )

    print("\n✅ Cloud sync (push) complete.", file=sys.stderr)


def pull():
    """Download database and FAISS index from Supabase Storage."""
    import httpx

    _check_credentials()

    files_to_download = {
        "memory.db": SQLITE_DB_PATH,
        "memory.index": FAISS_INDEX_PATH,
    }

    for remote_name, local_path in files_to_download.items():
        print(f"  Downloading {remote_name}...", file=sys.stderr)

        try:
            r = httpx.get(
                f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{remote_name}",
                headers=_headers(),
                timeout=120,
            )

            if r.status_code != 200:
                print(
                    f"  ❌ {remote_name} download failed ({r.status_code}): {r.text}",
                    file=sys.stderr,
                )
                continue

            # Ensure parent directory exists
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)

            with open(local_path, "wb") as f:
                f.write(r.content)

            size_mb = len(r.content) / (1024 * 1024)
            print(
                f"  ✅ {remote_name} downloaded ({size_mb:.1f} MB).",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"  ❌ {remote_name}: {e}", file=sys.stderr)

    print("\n✅ Cloud sync (pull) complete.", file=sys.stderr)


def status():
    """Check what files exist in the Supabase Storage bucket."""
    import httpx

    _check_credentials()

    print(f"\n📦 Checking bucket '{SUPABASE_BUCKET}'...\n", file=sys.stderr)

    r = httpx.post(
        f"{SUPABASE_URL}/storage/v1/object/list/{SUPABASE_BUCKET}",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"prefix": "", "limit": 100},
        timeout=30,
    )

    if r.status_code != 200:
        print(f"  ❌ Failed ({r.status_code}): {r.text}", file=sys.stderr)
        return

    files = r.json()
    if not files:
        print("  📭 Bucket is empty. Run 'python sync.py push' first.",
              file=sys.stderr)
        return

    print(f"  {'File':<20} {'Size':>10}  {'Last Modified'}", file=sys.stderr)
    print(f"  {'─'*20} {'─'*10}  {'─'*20}", file=sys.stderr)

    for f in files:
        name = f.get("name", "?")
        size = f.get("metadata", {}).get("size", 0)
        size_str = f"{size / (1024*1024):.1f} MB" if size else "?"
        updated = f.get("updated_at", "?")[:19]
        print(f"  {name:<20} {size_str:>10}  {updated}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("push", "pull", "status"):
        print("Usage: python sync.py [push|pull|status]")
        sys.exit(1)

    action = sys.argv[1]
    if action == "push":
        push()
    elif action == "pull":
        pull()
    elif action == "status":
        status()
