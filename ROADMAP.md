# Static Folder Publisher — Roadmap

Static Folder Publisher is an **EmaF205 project**.

The roadmap is intentionally small.

The goal is not to turn the project into a CMS.

The goal is to make this workflow better:

```text
finished HTML
    ↓
folders
    ↓
build
    ↓
complete static website
```

## Current — V1

Status: **working**

- HTML-first publishing
- folders become sections
- automatic homepage
- automatic section indexes
- nested sections
- navigation
- sitemap
- RSS
- 404 page
- metadata fallbacks
- draft handling
- local assets
- white-label output
- validation
- deterministic builds
- GitHub Actions CI
- GitHub Pages deployment
- Python 3.10–3.14 testing

## Next

Small improvements only.

Possible priorities:

- improve error messages
- improve documentation and examples
- expand tests for real-world folder structures
- improve generated structural-page accessibility
- make starter projects even easier to use
- improve deployment examples for common static hosts

## Later

Possible optional additions:

- Markdown input
- import adapters that convert external content into HTML
- additional deployment recipes
- small developer-quality-of-life improvements

These should remain optional and should not complicate the core.

## Not planned for the core

- visual page builder
- CMS dashboard
- authentication
- database
- server runtime
- ecommerce
- DOCX/PDF editing
- Google Docs editor
- Notion editor
- plugin marketplace

External tools may eventually convert content into HTML, but the publisher itself should stay focused.

## Guiding question

Before adding a feature, ask:

> Does this make publishing finished content through folders simpler without turning the project into a CMS?

If the answer is no, it probably does not belong in the core.

---

Created and maintained by **EmaF205**.
