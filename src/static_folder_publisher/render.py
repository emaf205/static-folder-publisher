from __future__ import annotations

import html
import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urljoin

from .models import Page, Section, SiteModel


class TemplateError(ValueError):
    pass


_TEMPLATE_TOKEN = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}")


DEFAULT_CSS = """:root {
  color-scheme: light;
  --background: #ffffff;
  --text: #111111;
  --muted: #666666;
  --line: #e8e8e8;
  --surface: #f7f7f7;
  --max: 72rem;
}
* { box-sizing: border-box; }
html { font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--background); color: var(--text); }
body { margin: 0; line-height: 1.6; }
a { color: inherit; text-underline-offset: .18em; }
.site-header, .shell { width: min(calc(100% - 2rem), var(--max)); margin-inline: auto; }
.site-header { padding-block: 1rem; border-bottom: 1px solid var(--line); }
.shell { padding-block: 3rem 5rem; }
.navigation { display: flex; gap: 1.5rem; align-items: flex-start; justify-content: space-between; }
.site-title { font-weight: 750; text-decoration: none; white-space: nowrap; }
.nav-tree { display: flex; gap: 1rem; flex-wrap: wrap; list-style: none; margin: 0; padding: 0; }
.nav-tree ul { list-style: none; margin: .4rem 0 0; padding-left: 1rem; }
.nav-tree a { text-decoration: none; }
.hero, .section-header { max-width: 48rem; margin-bottom: 3rem; }
h1 { font-size: clamp(2.2rem, 7vw, 5.5rem); line-height: .98; letter-spacing: -.04em; margin: 0 0 1rem; }
h2 { letter-spacing: -.02em; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr)); gap: 1rem; margin-block: 1rem 3rem; }
.card { border: 1px solid var(--line); border-radius: .8rem; padding: 1.25rem; }
.card h2 { margin: .35rem 0 .5rem; }
.card p { margin: .5rem 0 0; color: var(--muted); }
.meta, .eyebrow { font-size: .82rem; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
.breadcrumbs { margin-bottom: 2rem; color: var(--muted); font-size: .92rem; }
.breadcrumbs span { margin-inline: .3rem; }
.error-page { max-width: 42rem; }
@media (max-width: 48rem) {
  .navigation { display: block; }
  .nav-tree { display: block; margin-top: 1rem; }
  .nav-tree > li { margin-block: .5rem; }
}
"""

DEFAULT_HOME = """<!doctype html>
<html lang=\"{{lang}}\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
  <title>{{title}}</title>
  <meta name=\"description\" content=\"{{description_attr}}\">
  <link rel=\"canonical\" href=\"{{canonical}}\">
  <link rel=\"stylesheet\" href=\"{{css_href}}\">
</head>
<body>
  <header class=\"site-header\">{{navigation}}</header>
  <main class=\"shell\">{{content}}</main>
</body>
</html>
"""

DEFAULT_SECTION = """<!doctype html>
<html lang=\"{{lang}}\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
  <title>{{title}}</title>
  <meta name=\"description\" content=\"{{description_attr}}\">
  <link rel=\"canonical\" href=\"{{canonical}}\">
  <link rel=\"stylesheet\" href=\"{{css_href}}\">
</head>
<body>
  <header class=\"site-header\">{{navigation}}</header>
  <main class=\"shell\">
    {{breadcrumbs}}
    {{content}}
  </main>
</body>
</html>
"""

DEFAULT_404 = """<!doctype html>
<html lang=\"{{lang}}\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
  <title>Page not found</title>
  <meta name=\"robots\" content=\"noindex\">
  <link rel=\"stylesheet\" href=\"{{css_href}}\">
</head>
<body>
  <main class=\"shell error-page\">
    <p class=\"eyebrow\">404</p>
    <h1>Page not found</h1>
    <p>The page you requested does not exist.</p>
    <p><a href=\"{{home_href}}\">Return home</a></p>
  </main>
</body>
</html>
"""


_COMMON_INITIALISMS = {"ai", "api", "css", "gpt", "html", "http", "https", "js", "llm", "pdf", "rss", "seo", "ui", "url", "ux", "xml"}


def _pretty_word(word: str) -> str:
    lowered = word.lower()
    return lowered.upper() if lowered in _COMMON_INITIALISMS else lowered.capitalize()


def pretty_name(value: str) -> str:
    words = [w for w in value.replace("_", "-").split("-") if w]
    return " ".join(_pretty_word(word) for word in words) or "Section"


def _template(project_root: Path, name: str, fallback: str) -> str:
    path = project_root / "templates" / name
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise TemplateError(f"{path}: template must be UTF-8 encoded.") from exc
    return fallback


_TEMPLATE_ALLOWED: dict[str, set[str]] = {
    "home.html": {"lang", "title", "description", "description_attr", "canonical", "css_href", "navigation", "content"},
    "section.html": {"lang", "title", "description", "description_attr", "canonical", "css_href", "navigation", "breadcrumbs", "content"},
    "404.html": {"lang", "css_href", "home_href"},
}


def validate_templates(project_root: Path) -> None:
    template_dir = project_root / "templates"
    for name, allowed in _TEMPLATE_ALLOWED.items():
        path = template_dir / name
        if not path.exists():
            continue
        template = _template(project_root, name, "")
        tokens = set(_TEMPLATE_TOKEN.findall(template))
        unknown = sorted(tokens - allowed)
        if unknown:
            raise TemplateError(
                f"{path}: unknown template placeholder(s): "
                + ", ".join(f"{{{{{token}}}}}" for token in unknown)
            )


def _render_template(template: str, values: dict[str, str]) -> str:
    tokens = set(_TEMPLATE_TOKEN.findall(template))
    unknown = sorted(tokens - set(values))
    if unknown:
        raise TemplateError("Unknown template placeholder(s): " + ", ".join(f"{{{{{name}}}}}" for name in unknown))

    def replace_token(match: re.Match[str]) -> str:
        return values[match.group(1)]

    return _TEMPLATE_TOKEN.sub(replace_token, template)


def rel_href(from_output: PurePosixPath, to_output: PurePosixPath) -> str:
    from_dir = Path(*from_output.parent.parts)
    target = Path(*to_output.parts)
    value = os.path.relpath(target, from_dir if str(from_dir) != "." else Path("."))
    return quote(value.replace(os.sep, "/"), safe="/.")


def canonical(model: SiteModel, output_path: PurePosixPath) -> str:
    base = model.config.base_url.rstrip("/") + "/"
    rel = "" if output_path == PurePosixPath("index.html") else output_path.as_posix()
    return html.escape(urljoin(base, quote(rel)), quote=True)


def _section_sort(section: Section):
    return (section.order if section.order is not None else 10**9, section.title.lower(), section.path.as_posix())


def _page_sort(page: Page):
    ordinal = page.published.toordinal() if page.published else 0
    return (page.order if page.order is not None else 10**9, -ordinal, page.title.lower(), page.rel_path.as_posix())


def _nav_branch(model: SiteModel, section: Section, current_output: PurePosixPath) -> str:
    if not section.menu:
        return ""
    target = section.path / "index.html"
    href = html.escape(rel_href(current_output, target), quote=True)
    children = "".join(_nav_branch(model, child, current_output) for child in sorted(section.children, key=_section_sort) if child.menu)
    nested = f"<ul>{children}</ul>" if children else ""
    return f'<li><a href="{href}">{html.escape(section.title)}</a>{nested}</li>'


def navigation(model: SiteModel, current_output: PurePosixPath) -> str:
    home_href = html.escape(rel_href(current_output, PurePosixPath("index.html")), quote=True)
    root_sections = [s for s in model.sections.values() if s.depth == 1 and s.menu]
    branches = "".join(_nav_branch(model, s, current_output) for s in sorted(root_sections, key=_section_sort))
    nav_list = f'<ul class="nav-tree">{branches}</ul>' if branches and model.config.navigation_automatic else ""
    return (
        '<nav class="navigation" aria-label="Primary">'
        f'<a class="site-title" href="{home_href}">{html.escape(model.config.title)}</a>'
        f'{nav_list}</nav>'
    )


def breadcrumbs(model: SiteModel, section: Section, current_output: PurePosixPath) -> str:
    parts = section.path.parts
    pieces = [f'<a href="{html.escape(rel_href(current_output, PurePosixPath("index.html")), quote=True)}">Home</a>']
    for idx, part in enumerate(parts):
        path = PurePosixPath(*parts[: idx + 1])
        item = model.sections[path]
        if idx == len(parts) - 1:
            pieces.append(f"<span aria-current=\"page\">{html.escape(item.title)}</span>")
        else:
            href = html.escape(rel_href(current_output, path / "index.html"), quote=True)
            pieces.append(f'<a href="{href}">{html.escape(item.title)}</a>')
    return '<nav class="breadcrumbs" aria-label="Breadcrumb">' + " <span>/</span> ".join(pieces) + "</nav>"


def _section_cards(model: SiteModel, sections: list[Section], current_output: PurePosixPath) -> str:
    if not sections:
        return ""
    cards = []
    for section in sorted(sections, key=_section_sort):
        href = html.escape(rel_href(current_output, section.path / "index.html"), quote=True)
        desc = f"<p>{html.escape(section.description)}</p>" if section.description else ""
        cards.append(f'<article class="card"><h2><a href="{href}">{html.escape(section.title)}</a></h2>{desc}</article>')
    return '<div class="cards">' + "".join(cards) + "</div>"


def _page_cards(pages: list[Page], current_output: PurePosixPath) -> str:
    cards = []
    for page in sorted([p for p in pages if not p.draft and p.listed and not p.is_index and not p.is_404], key=_page_sort):
        href = html.escape(rel_href(current_output, page.rel_path), quote=True)
        date_html = f'<time datetime="{page.published.isoformat()}">{page.published.isoformat()}</time>' if page.published else ""
        desc = f"<p>{html.escape(page.description)}</p>" if page.description else ""
        meta = f'<p class="meta">{date_html}</p>' if date_html else ""
        cards.append(f'<article class="card">{meta}<h2><a href="{href}">{html.escape(page.title)}</a></h2>{desc}</article>')
    return '<div class="cards">' + "".join(cards) + "</div>" if cards else ""


def render_home(model: SiteModel) -> str:
    output = PurePosixPath("index.html")
    root_sections = [s for s in model.sections.values() if s.depth == 1]
    latest = sorted(
        [p for p in model.pages if not p.draft and p.listed and not p.is_index and not p.is_404],
        key=lambda p: (-(p.published.toordinal() if p.published else 0), p.title.lower()),
    )[:10]

    sections_html = _section_cards(model, root_sections, output)
    latest_html = _page_cards(latest, output)
    content = (
        f'<section class="hero"><h1>{html.escape(model.config.title)}</h1>'
        + (f'<p>{html.escape(model.config.description)}</p>' if model.config.description else "")
        + '</section>'
        + (f'<section><h2>Sections</h2>{sections_html}</section>' if sections_html else "")
        + (f'<section><h2>Latest</h2>{latest_html}</section>' if latest_html else "")
    )

    template = _template(model.project_root, "home.html", DEFAULT_HOME)
    return _render_template(template, {
        "lang": html.escape(model.config.language, quote=True),
        "title": html.escape(model.config.title),
        "description": html.escape(model.config.description),
        "description_attr": html.escape(model.config.description, quote=True),
        "canonical": canonical(model, output),
        "css_href": html.escape(rel_href(output, PurePosixPath("assets/site.css")), quote=True),
        "navigation": navigation(model, output),
        "content": content,
    })


def render_section(model: SiteModel, section: Section) -> str:
    output = section.path / "index.html"
    children = sorted(section.children, key=_section_sort)
    section_cards = _section_cards(model, children, output)
    page_cards = _page_cards(section.pages, output)
    body = (
        f'<header class="section-header"><h1>{html.escape(section.title)}</h1>'
        + (f'<p>{html.escape(section.description)}</p>' if section.description else "")
        + '</header>'
        + (f'<section><h2>Sections</h2>{section_cards}</section>' if section_cards else "")
        + (f'<section><h2>Pages</h2>{page_cards}</section>' if page_cards else "")
    )
    template = _template(model.project_root, "section.html", DEFAULT_SECTION)
    return _render_template(template, {
        "lang": html.escape(model.config.language, quote=True),
        "title": html.escape(section.title),
        "description": html.escape(section.description),
        "description_attr": html.escape(section.description, quote=True),
        "canonical": canonical(model, output),
        "css_href": html.escape(rel_href(output, PurePosixPath("assets/site.css")), quote=True),
        "navigation": navigation(model, output),
        "breadcrumbs": breadcrumbs(model, section, output),
        "content": body,
    })


def render_404(model: SiteModel) -> str:
    output = PurePosixPath("404.html")
    template = _template(model.project_root, "404.html", DEFAULT_404)
    return _render_template(template, {
        "lang": html.escape(model.config.language, quote=True),
        "css_href": html.escape(rel_href(output, PurePosixPath("assets/site.css")), quote=True),
        "home_href": html.escape(rel_href(output, PurePosixPath("index.html")), quote=True),
    })
