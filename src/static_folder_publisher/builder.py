from __future__ import annotations

import hashlib
import html
import shutil
from dataclasses import replace
from datetime import datetime, time, timezone
from email.utils import format_datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urljoin

from .config import normalize_base_url
from .discover import discover
from .models import Page, SiteModel
from .render import DEFAULT_CSS, TemplateError, render_404, render_home, render_section, validate_templates
from .validator import validate_output_links, validate_source_plan


class BuildError(ValueError):
    pass


def source_fingerprint(content_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in content_dir.rglob("*") if p.is_file()):
        digest.update(path.relative_to(content_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _copy_tree_files(source_root: Path, dest_root: Path, *, skip_section_json: bool = False) -> None:
    if not source_root.exists():
        return
    for source in sorted(p for p in source_root.rglob("*") if p.is_file()):
        rel = source.relative_to(source_root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if skip_section_json and source.name == "_section.json":
            continue
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _copy_content(model: SiteModel) -> None:
    page_map = {page.rel_path.as_posix(): page for page in model.pages}
    for source in sorted(p for p in model.content_dir.rglob("*") if p.is_file()):
        rel = PurePosixPath(source.relative_to(model.content_dir).as_posix())
        if any(part.startswith(".") for part in rel.parts):
            continue
        if source.name == "_section.json":
            continue
        if source.suffix.lower() == ".html":
            page = page_map.get(rel.as_posix())
            if page and page.draft:
                continue
        target = model.dist_dir.joinpath(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _absolute_url(model: SiteModel, path: PurePosixPath) -> str:
    base = model.config.base_url.rstrip("/") + "/"
    rel = "" if path == PurePosixPath("index.html") else path.as_posix()
    return urljoin(base, quote(rel))


def _sitemap_paths(model: SiteModel) -> list[PurePosixPath]:
    paths = {PurePosixPath("index.html")}
    for section in model.sections.values():
        paths.add(section.path / "index.html")
    for page in model.pages:
        if page.draft or page.is_404:
            continue
        paths.add(page.rel_path)
    return sorted(paths, key=lambda p: p.as_posix())


def _render_sitemap(model: SiteModel) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path in _sitemap_paths(model):
        lines.append(f"  <url><loc>{html.escape(_absolute_url(model, path))}</loc></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _rss_pages(model: SiteModel) -> list[Page]:
    pages = [
        p for p in model.pages
        if not p.draft and p.listed and not p.is_index and not p.is_404 and p.published is not None
    ]
    pages.sort(key=lambda p: (-(p.published.toordinal() if p.published else 0), p.title.lower(), p.rel_path.as_posix()))
    return pages[: model.config.feed_limit]


def _render_rss(model: SiteModel) -> str:
    items: list[str] = []
    for page in _rss_pages(model):
        assert page.published is not None
        pub_dt = datetime.combine(page.published, time(0, 0), tzinfo=timezone.utc)
        url = _absolute_url(model, page.rel_path)
        items.append(
            "    <item>\n"
            f"      <title>{html.escape(page.title)}</title>\n"
            f"      <link>{html.escape(url)}</link>\n"
            f"      <guid>{html.escape(url)}</guid>\n"
            f"      <description>{html.escape(page.description)}</description>\n"
            f"      <pubDate>{format_datetime(pub_dt)}</pubDate>\n"
            "    </item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        '  <channel>\n'
        f'    <title>{html.escape(model.config.title)}</title>\n'
        f'    <link>{html.escape(model.config.base_url)}</link>\n'
        f'    <description>{html.escape(model.config.description)}</description>\n'
        + ("\n".join(items) + "\n" if items else "")
        + '  </channel>\n'
        '</rss>\n'
    )


def _page_for(model: SiteModel, rel: PurePosixPath) -> Page | None:
    return next((p for p in model.pages if p.rel_path == rel and not p.draft), None)


def clean(project_root: Path) -> Path:
    dist = project_root.resolve() / "dist"
    if dist.is_symlink():
        dist.unlink()
    elif dist.exists():
        shutil.rmtree(dist)
    return dist


def validate_project(project_root: Path, *, base_url: str | None = None) -> tuple[SiteModel, list[str]]:
    try:
        model = discover(project_root)
        if base_url is not None:
            model.config = replace(model.config, base_url=normalize_base_url(base_url, "--base-url"))
        warnings = validate_source_plan(model)
        validate_templates(project_root)
    except (ValueError, OSError) as exc:
        raise BuildError(str(exc)) from exc
    return model, warnings


def build(project_root: Path, *, base_url: str | None = None) -> tuple[SiteModel, list[str]]:
    project_root = project_root.resolve()
    try:
        model, warnings = validate_project(project_root, base_url=base_url)
        before = source_fingerprint(model.content_dir)

        # dist is generated state: always recreate it completely.
        clean(project_root)
        model.dist_dir.mkdir(parents=True, exist_ok=True)

        _copy_content(model)
        _copy_tree_files(model.assets_dir, model.dist_dir / "assets")
        default_css = model.dist_dir / "assets/site.css"
        if not default_css.exists():
            _write(default_css, DEFAULT_CSS)

        # Generated home, unless content/index.html explicitly overrides it.
        home_override = _page_for(model, PurePosixPath("index.html"))
        if home_override is None:
            _write(model.dist_dir / "index.html", render_home(model))

        # Generate every section index unless a source index.html overrides it.
        for section in sorted(model.sections.values(), key=lambda s: (s.depth, s.path.as_posix())):
            override = _page_for(model, section.path / "index.html")
            if override is None:
                _write(model.dist_dir.joinpath(*section.path.parts) / "index.html", render_section(model, section))

        custom_404 = _page_for(model, PurePosixPath("404.html"))
        if custom_404 is None:
            _write(model.dist_dir / "404.html", render_404(model))

        if model.config.sitemap_enabled:
            _write(model.dist_dir / "sitemap.xml", _render_sitemap(model))
        if model.config.feed_enabled:
            _write(model.dist_dir / "rss.xml", _render_rss(model))

        after = source_fingerprint(model.content_dir)
        if before != after:
            raise BuildError("Source integrity failure: files under content/ changed during build.")

        if not (model.dist_dir / "index.html").exists():
            raise BuildError("Build produced no dist/index.html.")

        warnings.extend(validate_output_links(model.dist_dir))
        return model, warnings
    except BuildError:
        raise
    except TemplateError as exc:
        raise BuildError(str(exc)) from exc
    except (OSError, UnicodeError) as exc:
        raise BuildError(f"Build I/O failure: {exc}") from exc

