from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REDACTED = "<redacted>"
SENSITIVE_KEY_PATTERN = re.compile(
    r"(authorization|cookie|set-cookie|csrf|token|secret|session|visitor|device|credential|"
    r"trace|tracking|queryid|userquery|solid|solmetadata)",
    re.IGNORECASE,
)
BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
COOKIE_LINE_PATTERN = re.compile(r"(?im)^((?:set-)?cookie\s*)\n[^\n]+")
HEADER_VALUE_PATTERN = re.compile(
    r"(?im)^((?:authorization|x-csrf-token|x-seek-ec-sessionid|x-seek-ec-visitorid)\s*)\n[^\n]+"
)
COOKIE_PAIR_PATTERN = re.compile(
    r"(?i)(^|;\s*)([^=;\s]*(session|token|csrf|visitor|device)[^=;\s]*)=[^;]+"
)
UUID_SESSION_PATTERN = re.compile(
    r"(?i)\b(jobseeker(session|visitor)id|sessionid|visitorid|deviceid)=([a-f0-9-]{16,})"
)


def redact_text(text: str) -> str:
    redacted = BEARER_PATTERN.sub(f"Bearer {REDACTED}", text)
    redacted = COOKIE_LINE_PATTERN.sub(lambda match: f"{match.group(1)}\n{REDACTED}", redacted)
    redacted = HEADER_VALUE_PATTERN.sub(lambda match: f"{match.group(1)}\n{REDACTED}", redacted)
    redacted = COOKIE_PAIR_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}={REDACTED}", redacted
    )
    return UUID_SESSION_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED}", redacted)


def redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if SENSITIVE_KEY_PATTERN.search(str(key)) else redact_json(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def first_json_value(text: str) -> Any | None:
    decoder = json.JSONDecoder()
    candidates = []
    response_index = text.find("RESPONSE")
    if response_index >= 0:
        candidates.append(text[response_index + len("RESPONSE") :])
    candidates.append(text)

    for candidate in candidates:
        value = _first_json_value_in_text(candidate, decoder)
        if value is not None:
            return value
    return None


def _first_json_value_in_text(text: str, decoder: json.JSONDecoder) -> Any | None:
    for index, character in enumerate(text):
        if character not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    return None


def shrink_json(value: Any, max_items: int) -> Any:
    if isinstance(value, list):
        return [shrink_json(item, max_items) for item in value[:max_items]]
    if isinstance(value, dict):
        return {key: shrink_json(item, max_items) for key, item in value.items()}
    return value


def sanitize_file(
    source_path: Path, output_path: Path, *, max_items: int, max_text_chars: int
) -> None:
    raw_text = source_path.read_text(encoding="utf-8")
    json_value = first_json_value(raw_text)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if json_value is not None:
        sanitized = shrink_json(redact_json(json_value), max_items)
        output_path.write_text(
            json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return

    sanitized_text = redact_text(raw_text)[:max_text_chars].rstrip() + "\n"
    output_path.write_text(sanitized_text, encoding="utf-8")


def build_default_outputs(root: Path, max_items: int, max_text_chars: int) -> None:
    sources = {
        "dealls": "raw-response-dealls.txt",
        "glints": "raw-response-glints.txt",
        "jobstreet": "raw-response-jobstreet.txt",
        "kalibrr": "raw-response-kalibrr.txt",
    }
    for source, filename in sources.items():
        sanitize_file(
            root / filename,
            root / "tests" / "fixtures" / "raw" / source / "sample.json",
            max_items=max_items,
            max_text_chars=max_text_chars,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sanitize raw source captures into safe fixtures.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--max-items", type=int, default=2)
    parser.add_argument("--max-text-chars", type=int, default=20_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_default_outputs(args.root, args.max_items, args.max_text_chars)


if __name__ == "__main__":
    main()
