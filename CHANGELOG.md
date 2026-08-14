# Changelog

All notable changes to this project will be documented here.

## 1.0.1 — 2026-08-14

### Fixed

- Asset-only content directories no longer become website sections or navigation entries.
- Date fallback is deterministic: filename `YYYY-MM-DD` prefixes are supported and filesystem mtimes are no longer used.
- Invalid `site.baseUrl` values now fail validation instead of producing broken canonical, sitemap, or RSS URLs; embedded credentials and invalid ports are rejected.
- Exact, case-insensitive, Unicode-normalized and file-vs-directory output collisions are rejected before writing `dist/`, including generated structural files and global assets.
- `.HTML` source files are discovered case-insensitively.
- Symlinks under publishing inputs are rejected to avoid non-portable builds and accidental publication outside the project tree.
- Build-time I/O and template encoding errors are reported as clean build errors.
- Cleaning a symlinked `dist/` removes the symlink rather than following it.

### Improved

- Added tests for asset-only folders, explicit non-HTML sections, deterministic dates, hidden content, disabled navigation, invalid base URLs, and unreadable templates.
- Added a real zero-configuration minimal example.
- Added `--base-url` build/validate/serve overrides so CI can inject deployment URLs without editing source configuration.
- Common web initialisms such as AI, HTML, API and SEO are preserved in zero-config fallback names.
- Unknown configuration keys and unknown template placeholders now fail fast instead of being silently ignored.
- Expanded CI coverage to Python 3.10–3.14.
- Updated GitHub Pages workflow Actions and pinned GitHub-authored Actions to verified full commit SHAs.
- Reworked content discovery to a single filesystem snapshot, avoiding repeated recursive scans as site trees grow.

## 1.0.0 — 2026-08-14

### Added

- HTML-first, folder-based static publishing core.
- Read-only source workflow with disposable `dist/` output.
- Automatic homepage, section indexes, nested navigation and breadcrumbs.
- Metadata extraction with zero-configuration fallbacks.
- Draft and listing visibility controls.
- Section configuration through `_section.json`.
- Static asset preservation.
- Sitemap, RSS and 404 generation.
- `publisher build`, `validate`, `serve` and `clean` commands.
- Source integrity and repeatability tests.
- Optional GitHub Pages deployment workflow example.
