from __future__ import annotations

import re

from selectolax.parser import HTMLParser

_NOISE_SELECTORS = "script, style, noscript, template, iframe, svg"
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def html_to_text(html: str | None) -> str | None:
    if html is None:
        return None

    if not html.strip():
        return None

    tree = HTMLParser(html)
    for node in tree.css(_NOISE_SELECTORS):
        node.decompose()

    text = normalize_text(tree.text(deep=True, separator=" ", strip=True))
    return text or None


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = normalize_text(value)
    return text or None
