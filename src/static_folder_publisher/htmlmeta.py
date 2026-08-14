from __future__ import annotations

from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

from .models import Page


class MetadataError(ValueError):
    pass


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self._in_title = False
        self._in_h1 = False
        self._title_parts: list[str] = []
        self._h1_parts: list[str] = []
        self._have_h1 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            name = attr.get("name", "").strip().lower()
            if name:
                self.meta[name] = attr.get("content", "").strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "h1" and not self._have_h1:
            self._in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "h1" and self._in_h1:
            self._in_h1 = False
            self._have_h1 = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._in_h1:
            self._h1_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())

    @property
    def h1(self) -> str:
        return " ".join("".join(self._h1_parts).split())


_COMMON_INITIALISMS = {"ai", "api", "css", "gpt", "html", "http", "https", "js", "llm", "pdf", "rss", "seo", "ui", "url", "ux", "xml"}


def _pretty_filename(stem: str) -> str:
    parts = [part for part in stem.replace("_", "-").split("-") if part]
    pretty = []
    for part in parts:
        lowered = part.lower()
        pretty.append(lowered.upper() if lowered in _COMMON_INITIALISMS else lowered.capitalize())
    return " ".join(pretty) or "Untitled"


def _parse_bool(raw: Optional[str], default: bool, label: str, source: Path) -> bool:
    if raw is None or raw == "":
        return default
    value = raw.strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise MetadataError(f"{source}: meta '{label}' must be true or false, got {raw!r}.")


def _parse_order(raw: Optional[str], source: Path) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise MetadataError(f"{source}: meta 'order' must be an integer, got {raw!r}.") from exc


def _filename_date(source: Path) -> Optional[date]:
    """Return a deterministic YYYY-MM-DD prefix date, if present and valid."""
    prefix = source.stem[:10]
    if len(prefix) != 10 or prefix[4:5] != "-" or prefix[7:8] != "-":
        return None
    try:
        return date.fromisoformat(prefix)
    except ValueError:
        return None


def _parse_date(raw: Optional[str], source: Path) -> Optional[date]:
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise MetadataError(f"{source}: meta 'date' must be ISO-8601, got {raw!r}.") from exc

    # Do not fall back to filesystem mtime: Git checkouts do not preserve it,
    # which makes otherwise identical builds vary across environments.
    return _filename_date(source)


def parse_page(source: Path, rel_path) -> Page:
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise MetadataError(f"{source}: HTML must be UTF-8 encoded.") from exc
    except OSError as exc:
        raise MetadataError(f"Cannot read {source}: {exc}") from exc

    parser = _MetadataParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise MetadataError(f"Cannot parse {source}: {exc}") from exc

    meta = parser.meta
    title = meta.get("title", "").strip() or parser.title or parser.h1 or _pretty_filename(source.stem)
    description = meta.get("description", "").strip()

    return Page(
        source=source,
        rel_path=rel_path,
        title=title,
        description=description,
        published=_parse_date(meta.get("date"), source),
        draft=_parse_bool(meta.get("draft"), False, "draft", source),
        listed=_parse_bool(meta.get("index"), True, "index", source),
        order=_parse_order(meta.get("order"), source),
    )
