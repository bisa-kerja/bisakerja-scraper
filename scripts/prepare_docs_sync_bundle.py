from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

INTERNAL_MARKDOWN_LINK_PATTERN = re.compile(
    r"\]\((?!https?://|mailto:|#|/|data:)([^)\s]+\.md(?:#[^)]+)?)\)"
)


def rewrite_internal_markdown_links(content: str) -> str:
    def replace(match: re.Match[str]) -> str:
        link = match.group(1)
        file_path, separator, anchor = link.partition("#")
        if not file_path.endswith(".md"):
            return match.group(0)

        mdx_link = f"{file_path[:-3]}.mdx"
        if separator:
            mdx_link = f"{mdx_link}#{anchor}"
        return match.group(0).replace(link, mdx_link)

    return INTERNAL_MARKDOWN_LINK_PATTERN.sub(replace, content)


def convert_markdown_to_mdx(path: Path) -> Path:
    target = path.with_suffix(".mdx")
    content = rewrite_internal_markdown_links(path.read_text(encoding="utf-8"))
    target.write_text(content, encoding="utf-8")
    path.unlink()
    return target


def list_files(root: Path, suffix: str) -> list[Path]:
    return sorted(path for path in root.rglob(f"*{suffix}") if path.is_file())


def build_bundle(root: Path, output: Path, source_ref: str, source_sha: str) -> dict[str, object]:
    source_docs = root / "docs"
    if not source_docs.is_dir():
        raise SystemExit("docs directory is missing")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    shutil.copytree(source_docs, output, dirs_exist_ok=True)
    markdown_files = list_files(output, ".md")
    for markdown_file in markdown_files:
        convert_markdown_to_mdx(markdown_file)

    mdx_files = list_files(output, ".mdx")
    manifest = {
        "service": "scraper-api",
        "source_repo": "bisakerja-scraper",
        "source_ref": source_ref,
        "source_sha": source_sha,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sync_mode": "merge",
        "doc_count": len(mdx_files),
        "asset_count": 0,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare scraper docs sync bundle.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path(".tmp/docs-sync"))
    parser.add_argument("--source-ref", default="local")
    parser.add_argument("--source-sha", default="0000000000000000000000000000000000000000")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    output = args.output
    if not output.is_absolute():
        output = root / output

    manifest = build_bundle(root, output.resolve(), args.source_ref, args.source_sha)
    print(f"prepared docs sync bundle: {manifest['doc_count']} docs")


if __name__ == "__main__":
    main()
