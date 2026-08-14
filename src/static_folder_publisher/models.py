from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Optional


@dataclass(frozen=True)
class SiteConfig:
    title: str = "My Site"
    description: str = ""
    language: str = "en"
    base_url: str = "http://localhost"
    navigation_automatic: bool = True
    feed_enabled: bool = True
    feed_limit: int = 20
    sitemap_enabled: bool = True


@dataclass
class Page:
    source: Path
    rel_path: PurePosixPath
    title: str
    description: str = ""
    published: Optional[date] = None
    draft: bool = False
    listed: bool = True
    order: Optional[int] = None

    @property
    def is_index(self) -> bool:
        return self.rel_path.name.lower() == "index.html"

    @property
    def is_404(self) -> bool:
        return self.rel_path == PurePosixPath("404.html")

    @property
    def section_path(self) -> PurePosixPath:
        parent = self.rel_path.parent
        return PurePosixPath("") if str(parent) == "." else parent


@dataclass
class Section:
    path: PurePosixPath
    title: str
    description: str = ""
    menu: bool = True
    order: Optional[int] = None
    source_dir: Optional[Path] = None
    children: list["Section"] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)

    @property
    def depth(self) -> int:
        if not self.path.parts:
            return 0
        return len(self.path.parts)


@dataclass
class SiteModel:
    config: SiteConfig
    project_root: Path
    content_dir: Path
    assets_dir: Path
    dist_dir: Path
    pages: list[Page]
    sections: dict[PurePosixPath, Section]
    root_pages: list[Page]
    warnings: list[str] = field(default_factory=list)
