import json
import re
from pathlib import Path

from scripts.sanitize_raw_fixtures import REDACTED, redact_json, redact_text, sanitize_file

SECRET_PATTERN = re.compile(
    r"Bearer\s+(?!<redacted>)|sessionid=(?!<redacted>)|visitorid=(?!<redacted>)|"
    r"set-cookie\s*\n(?!<redacted>)",
    re.IGNORECASE,
)


def test_redact_text_removes_bearer_cookie_and_session_values() -> None:
    raw = "\n".join(
        [
            "authorization",
            "Bearer abc.def",
            "set-cookie",
            "JobseekerSessionId=f02aead2-61b0-45e4-a4b9-aa430e3ba4d4; Path=/",
        ]
    )

    redacted = redact_text(raw)

    assert f"authorization\n{REDACTED}" in redacted
    assert "set-cookie\n<redacted>" in redacted
    assert "f02aead2" not in redacted


def test_redact_json_recurses_sensitive_keys() -> None:
    assert redact_json({"headers": {"cookie": "a=b"}, "items": [{"token": "abc"}]}) == {
        "headers": {"cookie": REDACTED},
        "items": [{"token": REDACTED}],
    }


def test_sanitize_file_writes_parseable_json(tmp_path) -> None:
    source = tmp_path / "raw.txt"
    output = tmp_path / "sample.json"
    source.write_text(
        'HEADER\nauthorization\nBearer abc\nRESPONSE\n{"token":"abc","items":[1,2,3]}'
    )

    sanitize_file(source, output, max_items=2, max_text_chars=1_000)

    assert json.loads(output.read_text()) == {"items": [1, 2], "token": REDACTED}


def test_generated_raw_fixtures_have_no_secret_patterns() -> None:
    fixture_root = Path(__file__).parents[2] / "fixtures" / "raw"
    fixture_paths = sorted(fixture_root.glob("*/*"))

    assert fixture_paths
    for path in fixture_paths:
        text = path.read_text(encoding="utf-8")
        assert not SECRET_PATTERN.search(text), path
        if path.suffix == ".json":
            json.loads(text)
