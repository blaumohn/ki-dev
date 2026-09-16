"""Claude-JSONL lokal auswerten, ohne Modellaufruf oder Rohtexte."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

TOKEN_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


def summarize(path: Path, run_id: str) -> dict:
    requests = {}
    round_id = None
    failures = []
    tools = Counter()
    with path.open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            message = row.get("message", {})
            content = message.get("content")
            if row.get("type") == "user" and isinstance(content, str):
                match = re.match(
                    rf"Bauauftrag fuer Lauf {re.escape(run_id)}, "
                    r"Runde (\d+)\.",
                    content,
                )
                if match:
                    round_id = int(match[1])
                elif content.startswith("Bauauftrag fuer Lauf "):
                    round_id = None
            if round_id is None:
                continue
            if row.get("type") == "assistant":
                for block in (
                    content if isinstance(content, list) else []
                ):
                    if block.get("type") == "tool_use":
                        tools[round_id] += 1
                if (
                    message.get("usage")
                    and message.get("model") != "<synthetic>"
                ):
                    # Streaming kann dieselbe Modellantwort aufteilen.
                    requests[message["id"]] = (round_id, row)
            if row.get("isApiErrorMessage"):
                failures.append(
                    {
                        "timestamp": row.get("timestamp"),
                        "error": row.get("error"),
                        "status": row.get("apiErrorStatus"),
                        "rate_limit_type": row.get(
                            "quotaLimits", {}
                        ).get("rateLimitType"),
                    }
                )
    rounds = []
    total = Counter()
    for number in sorted({item[0] for item in requests.values()}):
        rows = [r for n, r in requests.values() if n == number]
        usage = Counter()
        contexts = []
        for row in rows:
            value = row["message"]["usage"]
            usage.update({key: value[key] for key in TOKEN_KEYS})
            contexts.append(sum(value[key] for key in TOKEN_KEYS[:-1]))
        total.update(usage)
        rounds.append(
            {
                "round_id": number,
                "requests": len(rows),
                "tool_calls": tools[number],
                "context_min": min(contexts),
                "context_max": max(contexts),
                "first_response": rows[0]["timestamp"],
                "last_response": rows[-1]["timestamp"],
                "usage": dict(usage),
            }
        )
    return {
        "run_id": run_id,
        "requests": len(requests),
        "usage": dict(total),
        "rounds": rounds,
        "failures": failures,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.transcript, args.run_id), indent=2))
