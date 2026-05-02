from __future__ import annotations

from pathlib import Path

from scripts.check_release_readiness import (
    check_doc_metadata,
    check_markdown_links,
    check_secret_patterns,
    run_checks,
)


def write_doc(path: Path, body: str = "See [other](./other.md).\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                "title: Example",
                "description: Example doc.",
                "owner: data-ingestion-owner",
                "reviewers:",
                "  - backend-owner",
                "doc_status: draft",
                "last_reviewed: 2026-05-02",
                "---",
                "",
                "# Example",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )


def test_check_doc_metadata_accepts_required_frontmatter(tmp_path) -> None:
    doc = tmp_path / "docs" / "example.md"
    write_doc(doc, body="Content.\n")

    assert check_doc_metadata(doc) == []


def test_check_doc_metadata_reports_missing_field(tmp_path) -> None:
    doc = tmp_path / "docs" / "example.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("---\ntitle: Example\n---\n# Example\n", encoding="utf-8")

    findings = check_doc_metadata(doc)

    assert any("missing frontmatter field: description" in finding.message for finding in findings)


def test_check_markdown_links_reports_broken_local_link(tmp_path) -> None:
    doc = tmp_path / "docs" / "example.md"
    write_doc(doc)

    findings = check_markdown_links(doc, tmp_path)

    assert findings[0].message == "broken local link: ./other.md"


def test_check_secret_patterns_allows_placeholders_and_flags_real_values(tmp_path) -> None:
    safe = tmp_path / "safe.md"
    unsafe = tmp_path / "unsafe.md"
    safe.write_text("authorization: <redacted>\nBearer <token>\n", encoding="utf-8")
    unsafe.write_text("authorization: Bearer abc.def\n", encoding="utf-8")

    assert check_secret_patterns(safe) == []
    assert check_secret_patterns(unsafe)


def test_run_checks_scans_docs_links_fixtures_and_raw_captures(tmp_path) -> None:
    doc = tmp_path / "docs" / "index.md"
    linked = tmp_path / "docs" / "other.md"
    fixture = tmp_path / "tests" / "fixtures" / "raw" / "source" / "sample.json"
    raw_capture = tmp_path / "raw-response-source.txt"
    env_example = tmp_path / ".env.example"
    write_doc(doc)
    write_doc(linked, body="Content.\n")
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"authorization":"<redacted>"}\n', encoding="utf-8")
    raw_capture.write_text("authorization\n<redacted>\n", encoding="utf-8")
    env_example.write_text("TOKEN=replace-with-placeholder\n", encoding="utf-8")

    assert run_checks(tmp_path) == []
