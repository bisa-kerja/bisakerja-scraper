from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

REQUIRED_FRONTMATTER_FIELDS = (
    "title",
    "description",
    "owner",
    "reviewers",
    "doc_status",
    "last_reviewed",
)

SECRET_PATTERNS = (
    re.compile(
        r"\bBearer\s+(?!<[^>]+>|replace-with)[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._~+/=-]+",
        re.I,
    ),
    re.compile(
        r"(?im)^[ \t]*(authorization|cookie|set-cookie)[ \t]*$\n(?![ \t]*<redacted>[ \t]*$).+"
    ),
    re.compile(r"(?i)\b(sessionid|visitorid|deviceid)=((?!<redacted>)[A-Za-z0-9._~%/-]{8,})"),
    re.compile(
        r"(?i)\b[A-Z0-9._%+-]+://[^:\s]+:"
        r"(?!(replace-with|example|local|test)[^@\s]*@)[^@\s]+@[^/\s]+"
    ),
)
HEADER_LINE_PATTERN = re.compile(r"(?i)^\s*(authorization|cookie|set-cookie)\s*:\s*(.+)$")
SAFE_PLACEHOLDER_PATTERN = re.compile(r"(?i)^(<[^>]+>|Bearer\s+<[^>]+>|replace-with.*)$")

MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FRONTMATTER_PATTERN = re.compile(r"\A---\n(.*?)\n---\n", re.S)


@dataclass(frozen=True)
class Finding:
    path: Path
    message: str


def iter_files(root: Path, patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(root.glob(pattern))
    return sorted(path for path in files if path.is_file())


def check_doc_metadata(path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(text)
    if match is None:
        return [Finding(path, "missing frontmatter")]

    frontmatter = match.group(1)
    findings: list[Finding] = []
    for field in REQUIRED_FRONTMATTER_FIELDS:
        if not re.search(rf"(?m)^{re.escape(field)}\s*:", frontmatter):
            findings.append(Finding(path, f"missing frontmatter field: {field}"))

    status_match = re.search(r"(?m)^doc_status\s*:\s*(\S+)", frontmatter)
    if status_match and status_match.group(1) not in {"draft", "active", "deprecated"}:
        findings.append(Finding(path, "invalid doc_status"))

    return findings


def check_markdown_links(path: Path, root: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    for target in MARKDOWN_LINK_PATTERN.findall(text):
        clean_target = target.strip()
        if not clean_target or clean_target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        link_path = clean_target.split("#", 1)[0]
        if not link_path:
            continue
        candidate = (path.parent / link_path).resolve()
        if not candidate.exists() or root.resolve() not in candidate.parents:
            findings.append(Finding(path, f"broken local link: {clean_target}"))
    return findings


def check_secret_patterns(path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    findings: list[Finding] = []
    for line in text.splitlines():
        header_match = HEADER_LINE_PATTERN.match(line)
        if header_match and not SAFE_PLACEHOLDER_PATTERN.match(header_match.group(2).strip()):
            findings.append(Finding(path, f"possible secret pattern: {line[:80]}"))
            return findings
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(Finding(path, f"possible secret pattern: {match.group(0)[:80]}"))
            break
    return findings


def run_checks(root: Path) -> list[Finding]:
    doc_files = iter_files(root, ["docs/**/*.md"])
    secret_scan_files = iter_files(
        root,
        [
            "docs/**/*.md",
            "tests/fixtures/**/*.json",
            "raw-response-*.txt",
            ".env.example",
        ],
    )

    findings: list[Finding] = []
    for path in doc_files:
        findings.extend(check_doc_metadata(path))
        findings.extend(check_markdown_links(path, root))
    for path in secret_scan_files:
        findings.extend(check_secret_patterns(path))
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate scraper docs metadata, local links, and secret-safe artifacts."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    findings = run_checks(root)
    if findings:
        for finding in findings:
            print(f"{finding.path.relative_to(root)}: {finding.message}")
        raise SystemExit(1)
    print("release readiness checks passed")


if __name__ == "__main__":
    main()
