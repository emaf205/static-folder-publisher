from __future__ import annotations

from pathlib import Path, PurePosixPath

from .config import ConfigError, load_section_config, load_site_config
from .htmlmeta import MetadataError, parse_page
from .models import Section, SiteModel
from .render import pretty_name


class DiscoveryError(ValueError):
    pass


def _rel_posix(path: Path, base: Path) -> PurePosixPath:
    return PurePosixPath(path.relative_to(base).as_posix())


def _is_hidden_relative(path: Path, base: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(base).parts)


def _add_directory_and_ancestors(candidates: set[Path], directory: Path, content_dir: Path) -> None:
    current = directory
    while current != content_dir and current.is_relative_to(content_dir):
        candidates.add(current)
        current = current.parent


def discover(project_root: Path) -> SiteModel:
    project_root = project_root.resolve()
    content_dir = project_root / "content"
    assets_dir = project_root / "assets"
    dist_dir = project_root / "dist"

    if not content_dir.exists() or not content_dir.is_dir():
        raise DiscoveryError(f"Missing content directory: {content_dir}")
    if content_dir.is_symlink():
        raise DiscoveryError("The content/ directory itself must not be a symlink.")

    # Walk content once. Reusing this snapshot avoids recursively rescanning every
    # directory when deciding whether it is structural or asset-only.
    try:
        all_entries = list(content_dir.rglob("*"))
    except OSError as exc:
        raise DiscoveryError(f"Cannot scan content directory {content_dir}: {exc}") from exc

    for source_path in all_entries:
        if source_path.is_symlink():
            rel = source_path.relative_to(content_dir).as_posix()
            raise DiscoveryError(f"Symlinks are not allowed under content/: {rel}")

    try:
        config = load_site_config(project_root)
    except ConfigError as exc:
        raise DiscoveryError(str(exc)) from exc

    visible_entries = [p for p in all_entries if not _is_hidden_relative(p, content_dir)]
    html_sources = sorted(
        p for p in visible_entries
        if p.is_file() and p.suffix.lower() == ".html"
    )

    pages = []
    for source in html_sources:
        rel = _rel_posix(source, content_dir)
        try:
            pages.append(parse_page(source, rel))
        except MetadataError as exc:
            raise DiscoveryError(str(exc)) from exc

    visible_direct_children: dict[Path, int] = {}
    visible_directories: list[Path] = []
    section_markers: list[Path] = []

    for entry in visible_entries:
        visible_direct_children[entry.parent] = visible_direct_children.get(entry.parent, 0) + 1
        if entry.is_dir():
            visible_directories.append(entry)
        elif entry.is_file() and entry.name == "_section.json":
            section_markers.append(entry)

    candidates: set[Path] = set()

    # Any folder containing publishable HTML (directly or below it) is structural.
    for source in html_sources:
        _add_directory_and_ancestors(candidates, source.parent, content_dir)

    # Explicit section markers make their directory structural even when it only
    # contains downloads/assets, and keep the ancestor tree connected.
    for marker in section_markers:
        if marker.parent != content_dir:
            _add_directory_and_ancestors(candidates, marker.parent, content_dir)

    # A truly empty *visible* directory is a zero-config section. Asset-only
    # directories have visible children and therefore stay out of the site tree.
    for directory in visible_directories:
        if visible_direct_children.get(directory, 0) == 0:
            _add_directory_and_ancestors(candidates, directory, content_dir)

    sections: dict[PurePosixPath, Section] = {}
    for directory in sorted(candidates):
        rel = _rel_posix(directory, content_dir)
        try:
            section_data = load_section_config(directory)
        except ConfigError as exc:
            raise DiscoveryError(str(exc)) from exc
        title = section_data.get("title") or pretty_name(rel.name)
        section = Section(
            path=rel,
            title=title.strip() or pretty_name(rel.name),
            description=(section_data.get("description") or "").strip(),
            menu=section_data.get("menu", True),
            order=section_data.get("order"),
            source_dir=directory,
        )
        sections[rel] = section

    # Attach nested sections.
    for path, section in sections.items():
        if len(path.parts) > 1:
            parent_path = PurePosixPath(*path.parts[:-1])
            parent = sections.get(parent_path)
            if parent:
                parent.children.append(section)

    root_pages = []
    for page in pages:
        if not page.section_path.parts:
            root_pages.append(page)
        else:
            section = sections.get(page.section_path)
            if section is None:
                raise DiscoveryError(
                    f"Internal error: section not found for {page.rel_path}. "
                    "HTML pages must live in structural content folders."
                )
            section.pages.append(page)

    return SiteModel(
        config=config,
        project_root=project_root,
        content_dir=content_dir,
        assets_dir=assets_dir,
        dist_dir=dist_dir,
        pages=pages,
        sections=sections,
        root_pages=root_pages,
    )
