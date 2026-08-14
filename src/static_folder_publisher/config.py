from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from .models import SiteConfig


class ConfigError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object.")
    return data


def _expect_bool(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{label} must be true or false.")


def _expect_int(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{label} must be an integer >= {minimum}.")
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        names = ", ".join(repr(name) for name in unknown)
        raise ConfigError(f"Unknown {label} field(s): {names}.")


def normalize_base_url(value: str, label: str = "site.baseUrl") -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ConfigError(f"{label} must not be empty.")
    if any(ch.isspace() for ch in normalized):
        raise ConfigError(f"{label} must not contain whitespace.")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ConfigError(f"{label} must be an absolute http:// or https:// URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError(f"{label} must not contain embedded credentials.")
    try:
        parsed.port
    except ValueError as exc:
        raise ConfigError(f"{label} contains an invalid port.") from exc
    if parsed.query or parsed.fragment:
        raise ConfigError(f"{label} must not contain a query string or fragment.")
    return normalized


def load_site_config(project_root: Path) -> SiteConfig:
    path = project_root / "config.json"
    if not path.exists():
        return SiteConfig()
    if path.is_symlink():
        raise ConfigError("config.json must not be a symlink.")

    data = _read_json(path)
    site = data.get("site", {})
    nav = data.get("navigation", {})
    feed = data.get("feed", {})
    sitemap = data.get("sitemap", {})

    for obj, name in ((site, "site"), (nav, "navigation"), (feed, "feed"), (sitemap, "sitemap")):
        if not isinstance(obj, dict):
            raise ConfigError(f"config.json field '{name}' must be an object.")

    _reject_unknown(data, {"site", "navigation", "feed", "sitemap"}, "config.json")
    _reject_unknown(site, {"title", "description", "language", "baseUrl"}, "site")
    _reject_unknown(nav, {"automatic"}, "navigation")
    _reject_unknown(feed, {"enabled", "limit"}, "feed")
    _reject_unknown(sitemap, {"enabled"}, "sitemap")

    title = site.get("title", "My Site")
    description = site.get("description", "")
    language = site.get("language", "en")
    base_url = site.get("baseUrl", "http://localhost")

    for value, label in ((title, "site.title"), (description, "site.description"), (language, "site.language"), (base_url, "site.baseUrl")):
        if not isinstance(value, str):
            raise ConfigError(f"{label} must be a string.")

    normalized_base = normalize_base_url(base_url)

    nav_auto = nav.get("automatic", True)
    feed_enabled = feed.get("enabled", True)
    feed_limit = feed.get("limit", 20)
    sitemap_enabled = sitemap.get("enabled", True)

    if not isinstance(nav_auto, bool):
        nav_auto = _expect_bool(nav_auto, "navigation.automatic")
    if not isinstance(feed_enabled, bool):
        feed_enabled = _expect_bool(feed_enabled, "feed.enabled")
    if not isinstance(sitemap_enabled, bool):
        sitemap_enabled = _expect_bool(sitemap_enabled, "sitemap.enabled")
    feed_limit = _expect_int(feed_limit, "feed.limit", 1)

    return SiteConfig(
        title=title.strip() or "My Site",
        description=description.strip(),
        language=language.strip() or "en",
        base_url=normalized_base,
        navigation_automatic=nav_auto,
        feed_enabled=feed_enabled,
        feed_limit=feed_limit,
        sitemap_enabled=sitemap_enabled,
    )


def load_section_config(section_dir: Path) -> dict[str, Any]:
    path = section_dir / "_section.json"
    if not path.exists():
        return {}
    data = _read_json(path)

    allowed = {"title", "description", "menu", "order"}
    _reject_unknown(data, allowed, str(path))
    result = data

    if "title" in result and not isinstance(result["title"], str):
        raise ConfigError(f"{path}: title must be a string.")
    if "description" in result and not isinstance(result["description"], str):
        raise ConfigError(f"{path}: description must be a string.")
    if "menu" in result and not isinstance(result["menu"], bool):
        raise ConfigError(f"{path}: menu must be true or false.")
    if "order" in result:
        if isinstance(result["order"], bool) or not isinstance(result["order"], int):
            raise ConfigError(f"{path}: order must be an integer.")
    return result
