from __future__ import annotations

import os
import unicodedata
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from .models import SiteModel


class ValidationError(ValueError):
    pass


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        data = {k.lower(): v for k, v in attrs if v is not None}
        for attr in ("href", "src"):
            if attr in data:
                self.refs.append((attr, data[attr]))


def _visible_relative(path: Path, root: Path) -> bool:
    return not any(part.startswith(".") for part in path.relative_to(root).parts)


def _page_map(model: SiteModel):
    return {page.rel_path.as_posix(): page for page in model.pages}


def _source_override(model: SiteModel, output_path: PurePosixPath) -> bool:
    page = next((p for p in model.pages if p.rel_path == output_path), None)
    return page is not None and not page.draft


def _planned_outputs(model: SiteModel) -> list[tuple[str, str]]:
    """Return (output path, producer) pairs before any destructive build step."""
    outputs: list[tuple[str, str]] = []
    pages = _page_map(model)

    # Files copied from content/.
    for source in sorted(p for p in model.content_dir.rglob("*") if p.is_file()):
        if not _visible_relative(source, model.content_dir):
            continue
        if source.name == "_section.json":
            continue
        rel = PurePosixPath(source.relative_to(model.content_dir).as_posix())
        if source.suffix.lower() == ".html":
            page = pages.get(rel.as_posix())
            if page is not None and page.draft:
                continue
        outputs.append((rel.as_posix(), f"content/{rel.as_posix()}"))

    # Global assets are copied under dist/assets/.
    if model.assets_dir.exists() and not model.assets_dir.is_symlink():
        for source in sorted(p for p in model.assets_dir.rglob("*") if p.is_file() and not p.is_symlink()):
            if not _visible_relative(source, model.assets_dir):
                continue
            rel = PurePosixPath(source.relative_to(model.assets_dir).as_posix())
            output = PurePosixPath("assets") / rel
            outputs.append((output.as_posix(), f"assets/{rel.as_posix()}"))

    # Generated structural files, unless an exact non-draft HTML override owns the path.
    generated: list[PurePosixPath] = []
    if not _source_override(model, PurePosixPath("index.html")):
        generated.append(PurePosixPath("index.html"))

    for section in model.sections.values():
        output = section.path / "index.html"
        if not _source_override(model, output):
            generated.append(output)

    if not _source_override(model, PurePosixPath("404.html")):
        generated.append(PurePosixPath("404.html"))
    if model.config.sitemap_enabled:
        generated.append(PurePosixPath("sitemap.xml"))
    if model.config.feed_enabled:
        generated.append(PurePosixPath("rss.xml"))

    for output in generated:
        outputs.append((output.as_posix(), f"generated:{output.as_posix()}"))

    return outputs


def validate_source_plan(model: SiteModel) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []

    # Symlinks make builds less portable and can accidentally publish files outside the project.
    for root, label in ((model.assets_dir, "assets"), (model.project_root / "templates", "templates")):
        if root.is_symlink():
            errors.append(f"The {label}/ directory itself must not be a symlink.")
        elif root.exists():
            for path in root.rglob("*"):
                if path.is_symlink():
                    rel = path.relative_to(root).as_posix()
                    errors.append(f"Symlinks are not allowed under {label}/: {rel}")

    # Detect exact, case-insensitive/Unicode-normalized, and file-vs-directory
    # collisions across copied and generated output. Every planned output is a file,
    # so `foo` and `foo/bar.html` cannot coexist in the same build tree.
    seen: dict[tuple[str, ...], tuple[str, str]] = {}
    descendant_of: dict[tuple[str, ...], tuple[str, str]] = {}

    for output, producer in _planned_outputs(model):
        path = PurePosixPath(output)
        key = tuple(unicodedata.normalize("NFC", part).casefold() for part in path.parts)

        previous = seen.get(key)
        if previous is not None:
            prev_output, prev_producer = previous
            if prev_output != output or prev_producer != producer:
                errors.append(
                    "Output collision: "
                    f"{prev_producer} -> {prev_output} conflicts with {producer} -> {output}."
                )
            continue

        # An already-planned file cannot be an ancestor directory of this output.
        ancestor_conflict = None
        for depth in range(1, len(key)):
            ancestor = key[:depth]
            if ancestor in seen:
                ancestor_conflict = seen[ancestor]
                break
        if ancestor_conflict is not None:
            prev_output, prev_producer = ancestor_conflict
            errors.append(
                "Output path-type collision: "
                f"{prev_producer} -> {prev_output} is a file but {producer} -> {output} "
                "requires it to be a directory."
            )
            continue

        # Conversely, this file cannot replace a directory required by a previously
        # planned descendant output.
        descendant_conflict = descendant_of.get(key)
        if descendant_conflict is not None:
            prev_output, prev_producer = descendant_conflict
            errors.append(
                "Output path-type collision: "
                f"{producer} -> {output} is a file but {prev_producer} -> {prev_output} "
                "requires it to be a directory."
            )
            continue

        seen[key] = (output, producer)
        for depth in range(1, len(key)):
            descendant_of.setdefault(key[:depth], (output, producer))

    # Warn about production builds still using the local default URL.
    if model.config.base_url.rstrip("/") == "http://localhost":
        warnings.append("site.baseUrl is using the local default http://localhost; set it before production deployment.")

    if errors:
        raise ValidationError("\n".join(errors))
    return warnings


def _resolve_local(dist: Path, html_file: Path, raw_ref: str) -> Path | None:
    ref = raw_ref.strip()
    if not ref or ref.startswith("#") or ref.startswith("//"):
        return None
    split = urlsplit(ref)
    if split.scheme or split.netloc:
        return None
    if split.path == "":
        return None
    path = unquote(split.path)
    if path.startswith("/"):
        target = dist / path.lstrip("/")
    else:
        target = html_file.parent / path
    target = Path(os.path.normpath(target))
    if target.is_dir():
        target = target / "index.html"
    elif path.endswith("/"):
        target = target / "index.html"
    return target


def validate_output_links(dist: Path) -> list[str]:
    warnings: list[str] = []
    if not dist.exists():
        return ["dist does not exist; output links were not checked."]

    html_files = [p for p in dist.rglob("*") if p.is_file() and p.suffix.lower() == ".html"]
    for html_file in sorted(html_files):
        try:
            text = html_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            warnings.append(f"Could not inspect links in {html_file.relative_to(dist)}")
            continue
        parser = _LinkParser()
        try:
            parser.feed(text)
        except Exception:
            warnings.append(f"Could not fully parse links in {html_file.relative_to(dist)}")
            continue
        for attr, ref in parser.refs:
            target = _resolve_local(dist, html_file, ref)
            if target is None:
                continue
            try:
                target.resolve().relative_to(dist.resolve())
            except ValueError:
                warnings.append(f"{html_file.relative_to(dist)}: {attr} escapes dist: {ref}")
                continue
            if not target.exists():
                warnings.append(f"{html_file.relative_to(dist)}: missing local target for {attr}={ref!r}")
    return warnings
