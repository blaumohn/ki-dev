import json

from scripts.analyze_claude_usage import summarize


def test_streaming_blocks_counted_once_and_setup_excluded(tmp_path):
    usage = {
        "input_tokens": 2,
        "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 100,
        "output_tokens": 30,
    }
    reply = {
        "type": "assistant",
        "timestamp": "2026-09-16T12:41:00Z",
        "message": {
            "id": "message-1",
            "model": "claude",
            "usage": usage,
        },
    }
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                reply,
                {
                    "type": "user",
                    "message": {
                        "content": (
                            "Bauauftrag fuer Lauf run-1, Runde 1."
                        ),
                    },
                },
                reply,
                reply,
                {
                    "type": "assistant",
                    "isApiErrorMessage": True,
                    "error": "rate_limit",
                    "apiErrorStatus": 429,
                    "quotaLimits": {"rateLimitType": "five_hour"},
                    "message": {"model": "<synthetic>", "usage": usage},
                },
            ]
        )
    )
    result = summarize(path, "run-1")
    assert result["requests"] == 1
    assert result["usage"] == usage
    assert result["rounds"][0]["context_max"] == 112
    assert result["failures"][0]["rate_limit_type"] == "five_hour"
