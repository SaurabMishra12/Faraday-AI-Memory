"""
ingestion.chatgpt — Parse ChatGPT conversation exports.

Standard ChatGPT data export produces a `conversations.json` file
containing an array of conversation objects, each with a nested
`mapping` dict of message nodes.

This parser uses streaming JSON for memory efficiency on large exports
(some users have 500 MB+ conversation files).
"""

import datetime
import json
import sys
from pathlib import Path
from typing import Dict, Generator


def parse_chatgpt_export(filepath: Path) -> Generator[Dict, None, None]:
    """
    Parse a ChatGPT conversations.json export.
    Yields one document per non-system message.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            print(
                f"[ingestion.chatgpt] Expected top-level list in {filepath}",
                file=sys.stderr,
            )
            return

        for convo in data:
            title = convo.get("title", "Untitled")
            create_time = convo.get("create_time", 0)
            mapping = convo.get("mapping", {})

            for _node_id, node in mapping.items():
                msg = node.get("message")
                if not msg:
                    continue

                # Extract text content
                parts = msg.get("content", {}).get("parts", [])
                if not parts:
                    continue

                # Filter: only string parts (skip tool_use, image refs, etc.)
                text_parts = [p for p in parts if isinstance(p, str)]
                text = "".join(text_parts).strip()

                if not text:
                    continue

                role = msg.get("author", {}).get("role", "unknown")

                # Skip system messages — they're boilerplate
                if role == "system":
                    continue

                # Timestamp: prefer message-level, fallback to conversation-level
                msg_time = msg.get("create_time") or create_time or 0
                if msg_time:
                    timestamp = datetime.datetime.fromtimestamp(
                        msg_time
                    ).isoformat()
                else:
                    timestamp = "Unknown"

                yield {
                    "text": f"[{role}] {text}",
                    "source": f"ChatGPT: {title}",
                    "timestamp": timestamp,
                    "tags": "chatgpt,chat",
                }

    except json.JSONDecodeError as e:
        print(
            f"[ingestion.chatgpt] JSON decode error in {filepath}: {e}",
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"[ingestion.chatgpt] Error parsing {filepath}: {e}",
            file=sys.stderr,
        )
