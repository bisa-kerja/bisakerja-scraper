from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser as StdHTMLParser

from selectolax.parser import HTMLParser as SelectolaxHTMLParser

_NOISE_SELECTORS = "script, style, noscript, template, iframe, svg"
_WHITESPACE_RE = re.compile(r"\s+")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_BULLET_LINE_PATTERN = re.compile(r"^\s*(?:[-*•]|[0-9]{1,3}[.)])\s+")
_ALLOWED_DISPLAY_TAGS = frozenset({"p", "ul", "ol", "li", "strong", "em", "br"})
_DROP_CONTENT_TAGS = frozenset(
    {"script", "style", "noscript", "template", "iframe", "object", "embed", "svg"}
)


def normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def html_to_text(html: str | None) -> str | None:
    if html is None:
        return None

    if not html.strip():
        return None

    tree = SelectolaxHTMLParser(html)
    for node in tree.css(_NOISE_SELECTORS):
        node.decompose()

    text = normalize_text(tree.text(deep=True, separator=" ", strip=True))
    return text or None


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = normalize_text(value)
    return text or None


class _DisplayHTMLSanitizer(StdHTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._open_tags: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        lowered = tag.casefold()
        if lowered in _DROP_CONTENT_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth > 0:
            return
        if lowered not in _ALLOWED_DISPLAY_TAGS:
            return
        if lowered == "br":
            self._parts.append("<br>")
            return
        self._parts.append(f"<{lowered}>")
        self._open_tags.append(lowered)

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: ANN001
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in _DROP_CONTENT_TAGS:
            if self._drop_depth > 0:
                self._drop_depth -= 1
            return
        if self._drop_depth > 0:
            return
        if lowered not in _ALLOWED_DISPLAY_TAGS or lowered == "br":
            return
        if lowered not in self._open_tags:
            return
        while self._open_tags:
            top = self._open_tags.pop()
            self._parts.append(f"</{top}>")
            if top == lowered:
                break

    def handle_data(self, data: str) -> None:
        if self._drop_depth > 0:
            return
        normalized = _WHITESPACE_RE.sub(" ", data)
        if not normalized.strip():
            return
        if self._parts and not self._parts[-1].endswith((">", " ")):
            if not normalized.startswith(" "):
                self._parts.append(" ")
        elif not self._parts:
            normalized = normalized.lstrip()
        if not normalized:
            return
        escaped = escape(normalized, quote=False)
        if self._parts and self._parts[-1] == " " and escaped.startswith(" "):
            escaped = escaped.lstrip()
        if not escaped:
            self._parts.append(" ")
            return
        self._parts.append(escaped)

    def get_sanitized_html(self) -> str:
        while self._open_tags:
            self._parts.append(f"</{self._open_tags.pop()}>")
        return "".join(self._parts)


def sanitize_display_html(value: str | None) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    parser = _DisplayHTMLSanitizer()
    parser.feed(text)
    parser.close()
    sanitized = parser.get_sanitized_html().strip()
    return sanitized or None


def text_to_display_html(value: str | None) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    text = clean_text(value)
    if text is None:
        return None
    lines = [line.strip() for line in value.splitlines()] if value is not None else []
    bullet_lines = [line for line in lines if _BULLET_LINE_PATTERN.match(line)]
    if len(bullet_lines) >= 2:
        items = [
            clean_text(_BULLET_LINE_PATTERN.sub("", line, count=1))
            for line in bullet_lines
            if line.strip()
        ]
        filtered_items = [item for item in items if item]
        if filtered_items:
            list_items = "".join(f"<li>{escape(item, quote=False)}</li>" for item in filtered_items)
            return f"<ul>{list_items}</ul>"
    return f"<p>{escape(text, quote=False)}</p>"


def ensure_display_html(value: str | None) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    if _HTML_TAG_PATTERN.search(value):
        sanitized = sanitize_display_html(value)
        if sanitized is not None:
            return sanitized
    return text_to_display_html(value)
