from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from static_folder_publisher.builder import BuildError, build, clean, source_fingerprint, validate_project
from static_folder_publisher.cli import build_parser


HTML = """<!doctype html><html><head><meta charset=\"utf-8\"><title>{title}</title>{meta}</head><body><h1>{title}</h1>{body}</body></html>"""


def write_page(path: Path, title: str, *, meta: str = "", body: str = "<p>Body</p>") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HTML.format(title=title, meta=meta, body=body), encoding="utf-8")


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class PublisherTests(unittest.TestCase):
    def project(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "content").mkdir()
        return temp, root

    def test_zero_config_single_page(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        source = root / "content/articles/hello.html"
        write_page(source, "Hello")
        original = source.read_bytes()

        model, warnings = build(root)

        self.assertTrue((root / "dist/index.html").exists())
        self.assertTrue((root / "dist/articles/index.html").exists())
        self.assertTrue((root / "dist/articles/hello.html").exists())
        self.assertEqual(original, (root / "dist/articles/hello.html").read_bytes())
        self.assertTrue((root / "dist/sitemap.xml").exists())
        self.assertTrue((root / "dist/rss.xml").exists())
        self.assertTrue((root / "dist/404.html").exists())
        self.assertTrue((root / "dist/assets/site.css").exists())
        self.assertFalse(any("assets/site.css" in warning for warning in warnings))
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(len(model.sections), 1)

    def test_nested_and_empty_folders_generate_indexes(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        (root / "content/empty").mkdir()
        write_page(root / "content/resources/prompts/useful.html", "Useful")

        build(root)

        self.assertTrue((root / "dist/empty/index.html").exists())
        self.assertTrue((root / "dist/resources/index.html").exists())
        self.assertTrue((root / "dist/resources/prompts/index.html").exists())

    def test_draft_and_listing_visibility(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(
            root / "content/blog/draft.html",
            "Draft",
            meta='<meta name="draft" content="true"><meta name="date" content="2026-08-14">',
        )
        write_page(
            root / "content/blog/unlisted.html",
            "Unlisted",
            meta='<meta name="index" content="false"><meta name="date" content="2026-08-13">',
        )
        write_page(
            root / "content/blog/public.html",
            "Public",
            meta='<meta name="date" content="2026-08-12">',
        )

        build(root)

        self.assertFalse((root / "dist/blog/draft.html").exists())
        self.assertTrue((root / "dist/blog/unlisted.html").exists())
        section = (root / "dist/blog/index.html").read_text(encoding="utf-8")
        self.assertNotIn("Draft", section)
        self.assertNotIn("Unlisted", section)
        self.assertIn("Public", section)
        rss = (root / "dist/rss.xml").read_text(encoding="utf-8")
        self.assertNotIn("Draft", rss)
        self.assertNotIn("Unlisted", rss)
        sitemap = (root / "dist/sitemap.xml").read_text(encoding="utf-8")
        self.assertNotIn("draft.html", sitemap)
        self.assertIn("unlisted.html", sitemap)

    def test_source_integrity(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")
        (root / "content/a/image.txt").write_text("asset", encoding="utf-8")
        before = source_fingerprint(root / "content")
        build(root)
        after = source_fingerprint(root / "content")
        self.assertEqual(before, after)

    def test_assets_preserved(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page", body='<img src="page-assets/pixel.svg" alt="">')
        (root / "content/a/page-assets").mkdir()
        (root / "content/a/page-assets/pixel.svg").write_text("<svg></svg>", encoding="utf-8")
        (root / "assets").mkdir()
        (root / "assets/global.txt").write_text("global", encoding="utf-8")

        build(root)

        self.assertEqual((root / "dist/a/page-assets/pixel.svg").read_text(), "<svg></svg>")
        self.assertEqual((root / "dist/assets/global.txt").read_text(), "global")

    def test_custom_home_section_and_404_are_not_overwritten(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/index.html", "Custom Home", body="CUSTOM-HOME")
        write_page(root / "content/guides/index.html", "Custom Guides", body="CUSTOM-GUIDES")
        write_page(root / "content/guides/page.html", "Page")
        write_page(root / "content/404.html", "Custom 404", body="CUSTOM-404")

        originals = {
            p.relative_to(root / "content").as_posix(): p.read_bytes()
            for p in (root / "content").rglob("*.html")
        }
        build(root)

        self.assertEqual((root / "dist/index.html").read_bytes(), originals["index.html"])
        self.assertEqual((root / "dist/guides/index.html").read_bytes(), originals["guides/index.html"])
        self.assertEqual((root / "dist/404.html").read_bytes(), originals["404.html"])

    def test_section_config_controls_navigation_and_order(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/zeta/page.html", "Z")
        write_page(root / "content/alpha/page.html", "A")
        write_page(root / "content/hidden/page.html", "H")
        (root / "content/zeta/_section.json").write_text(json.dumps({"title": "Zeta", "order": 1}), encoding="utf-8")
        (root / "content/alpha/_section.json").write_text(json.dumps({"title": "Alpha", "order": 2}), encoding="utf-8")
        (root / "content/hidden/_section.json").write_text(json.dumps({"title": "Hidden", "menu": False}), encoding="utf-8")

        build(root)
        home = (root / "dist/index.html").read_text(encoding="utf-8")
        nav = home.split('</nav>', 1)[0]
        self.assertLess(nav.index("Zeta"), nav.index("Alpha"))
        self.assertNotIn("Hidden", nav)
        self.assertIn("Hidden", home)  # still a public section/card

    def test_reserved_generated_file_collision_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")
        (root / "content/sitemap.xml").write_text("custom", encoding="utf-8")
        with self.assertRaises(BuildError):
            build(root)

    def test_invalid_metadata_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page", meta='<meta name="draft" content="sometimes">')
        with self.assertRaises(BuildError):
            build(root)

    def test_repeat_build_is_reproducible(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page", meta='<meta name="date" content="2026-08-14">')
        build(root)
        first = tree_hash(root / "dist")
        build(root)
        second = tree_hash(root / "dist")
        self.assertEqual(first, second)

    def test_missing_local_link_is_reported_as_warning(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page", body='<a href="missing.html">Missing</a>')
        _, warnings = build(root)
        self.assertTrue(any("missing.html" in warning for warning in warnings))

    def test_generated_links_encode_spaces(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/my section/a page.html", "A Page", meta='<meta name="date" content="2026-08-14">')
        build(root)
        home = (root / "dist/index.html").read_text(encoding="utf-8")
        section = (root / "dist/my section/index.html").read_text(encoding="utf-8")
        self.assertIn("my%20section/index.html", home)
        self.assertIn("a%20page.html", section)

    def test_generated_output_is_white_label(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page", meta='<meta name="date" content="2026-08-14">')
        build(root)
        generated = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in (root / "dist").rglob("*")
            if p.is_file() and p.suffix.lower() in {".html", ".xml", ".css"}
        )
        self.assertNotIn("Static Folder Publisher", generated)
        self.assertNotIn("EMAF205", generated)


    def test_asset_only_directories_are_not_sections(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/articles/page.html", "Page", body='<img src="page-assets/pixel.svg" alt="">')
        (root / "content/articles/page-assets").mkdir()
        (root / "content/articles/page-assets/pixel.svg").write_text("<svg></svg>", encoding="utf-8")

        model, _ = build(root)

        self.assertIn("articles", {p.as_posix() for p in model.sections})
        self.assertNotIn("articles/page-assets", {p.as_posix() for p in model.sections})
        self.assertFalse((root / "dist/articles/page-assets/index.html").exists())
        self.assertTrue((root / "dist/articles/page-assets/pixel.svg").exists())
        generated = (root / "dist/articles/index.html").read_text(encoding="utf-8")
        self.assertNotIn("Page Assets", generated)

    def test_section_marker_forces_non_html_directory_to_be_section(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        section = root / "content/downloads"
        section.mkdir(parents=True)
        (section / "_section.json").write_text(json.dumps({"title": "Downloads"}), encoding="utf-8")
        (section / "guide.pdf").write_bytes(b"not-a-real-pdf")

        model, _ = build(root)

        self.assertIn("downloads", {p.as_posix() for p in model.sections})
        self.assertTrue((root / "dist/downloads/index.html").exists())
        self.assertTrue((root / "dist/downloads/guide.pdf").exists())

    def test_undated_page_does_not_depend_on_mtime(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        page = root / "content/articles/undated.html"
        write_page(page, "Undated")
        page.touch()
        first_model, _ = build(root)
        first = next(p for p in first_model.pages if p.title == "Undated").published

        # A filesystem timestamp change must not change content metadata or output.
        import os
        os.utime(page, (1_000_000_000, 1_000_000_000))
        second_model, _ = build(root)
        second = next(p for p in second_model.pages if p.title == "Undated").published

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertNotIn("Undated", (root / "dist/rss.xml").read_text(encoding="utf-8"))

    def test_filename_date_prefix_is_deterministic_fallback(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/articles/2026-08-14-release-note.html", "Release Note")

        model, _ = build(root)
        page = next(p for p in model.pages if p.title == "Release Note")

        self.assertEqual(page.published.isoformat(), "2026-08-14")
        self.assertIn("Release Note", (root / "dist/rss.xml").read_text(encoding="utf-8"))

    def test_invalid_base_url_fails_validation(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")
        (root / "config.json").write_text(json.dumps({"site": {"baseUrl": "example.com/site"}}), encoding="utf-8")

        with self.assertRaises(BuildError):
            build(root)

    def test_navigation_can_be_disabled(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/articles/page.html", "Page")
        (root / "config.json").write_text(json.dumps({"navigation": {"automatic": False}}), encoding="utf-8")

        build(root)
        home = (root / "dist/index.html").read_text(encoding="utf-8")
        nav = home.split("</nav>", 1)[0]
        self.assertNotIn("Articles", nav)
        self.assertIn("My Site", nav)

    def test_hidden_content_is_not_published(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/public/page.html", "Public")
        write_page(root / "content/.private/secret.html", "Secret")
        (root / "content/.private/secret.txt").write_text("secret", encoding="utf-8")

        build(root)

        self.assertTrue((root / "dist/public/page.html").exists())
        self.assertFalse((root / "dist/.private/secret.html").exists())
        self.assertFalse((root / "dist/.private/secret.txt").exists())

    def test_non_utf8_custom_template_is_clean_build_error(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")
        (root / "templates").mkdir()
        (root / "templates/home.html").write_bytes(b"\xff\xfe")

        with self.assertRaises(BuildError):
            validate_project(root)


    def test_uppercase_html_extension_is_discovered(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/articles/PAGE.HTML", "Uppercase Extension", meta='<meta name="date" content="2026-08-14">')

        model, _ = build(root)

        self.assertTrue(any(p.rel_path.as_posix() == "articles/PAGE.HTML" for p in model.pages))
        self.assertTrue((root / "dist/articles/PAGE.HTML").exists())
        self.assertIn("Uppercase Extension", (root / "dist/articles/index.html").read_text(encoding="utf-8"))

    def test_case_insensitive_collision_with_generated_index_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/INDEX.HTML", "Uppercase Index")

        with self.assertRaises(BuildError):
            build(root)

    def test_global_asset_and_content_output_collision_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")
        (root / "content/assets").mkdir()
        (root / "content/assets/logo.svg").write_text("content", encoding="utf-8")
        (root / "assets").mkdir()
        (root / "assets/logo.svg").write_text("global", encoding="utf-8")

        with self.assertRaises(BuildError):
            build(root)


    def test_base_url_subpath_is_preserved_in_canonical_and_sitemap(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/articles/page.html", "Page", meta='<meta name="date" content="2026-08-14">')
        (root / "config.json").write_text(
            json.dumps({"site": {"baseUrl": "https://example.com/project", "title": "Example"}}),
            encoding="utf-8",
        )

        build(root)
        home = (root / "dist/index.html").read_text(encoding="utf-8")
        section = (root / "dist/articles/index.html").read_text(encoding="utf-8")
        sitemap = (root / "dist/sitemap.xml").read_text(encoding="utf-8")

        self.assertIn('href="https://example.com/project/"', home)
        self.assertIn('href="https://example.com/project/articles/index.html"', section)
        self.assertIn("https://example.com/project/articles/page.html", sitemap)


    def test_common_initialisms_are_preserved_in_fallback_names(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        page = root / "content/ai-experiments/html-api-guide.html"
        page.parent.mkdir(parents=True)
        page.write_text('<!doctype html><html><body><p>No explicit title</p></body></html>', encoding="utf-8")

        model, _ = build(root)
        section = next(s for s in model.sections.values() if s.path.as_posix() == "ai-experiments")
        parsed = next(p for p in model.pages if p.rel_path.as_posix().endswith("html-api-guide.html"))

        self.assertEqual(section.title, "AI Experiments")
        self.assertEqual(parsed.title, "HTML API Guide")


    def test_unknown_site_config_field_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")
        (root / "config.json").write_text(json.dumps({"site": {"base_url": "https://example.com"}}), encoding="utf-8")

        with self.assertRaises(BuildError):
            build(root)

    def test_unknown_section_config_field_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")
        (root / "content/a/_section.json").write_text(json.dumps({"titel": "Typo"}), encoding="utf-8")

        with self.assertRaises(BuildError):
            build(root)


    def test_content_symlink_is_rejected(self):
        import os
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        target = root / "outside.html"
        write_page(target, "Outside")
        link = root / "content/leak.html"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable on this platform")

        with self.assertRaises(BuildError):
            build(root)

    def test_clean_unlinks_dist_symlink_without_deleting_target(self):
        import os
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        target = root / "outside-dist"
        target.mkdir()
        sentinel = target / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        link = root / "dist"
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable on this platform")

        clean(root)

        self.assertFalse(link.exists())
        self.assertTrue(sentinel.exists())


    def test_project_option_works_before_or_after_command(self):
        parser = build_parser()
        before = parser.parse_args(["--project", "/tmp/example", "build"])
        after = parser.parse_args(["build", "--project", "/tmp/example", "--base-url", "https://example.com/site"])

        self.assertEqual(before.project, "/tmp/example")
        self.assertIsNone(before.project_after)
        self.assertEqual(after.project, ".")
        self.assertEqual(after.project_after, "/tmp/example")
        self.assertEqual(after.base_url, "https://example.com/site")


    def test_base_url_cli_override_does_not_modify_config(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/articles/page.html", "Page", meta='<meta name="date" content="2026-08-14">')
        config = {"site": {"baseUrl": "http://localhost", "title": "Example"}}
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        before = config_path.read_bytes()

        build(root, base_url="https://example.com/project")

        self.assertEqual(before, config_path.read_bytes())
        sitemap = (root / "dist/sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("https://example.com/project/articles/page.html", sitemap)
        self.assertNotIn("http://localhost", sitemap)

    def test_invalid_base_url_override_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")

        with self.assertRaises(BuildError):
            build(root, base_url="not-a-url")


    def test_nested_empty_section_keeps_ancestor_indexes(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        (root / "content/parent/child").mkdir(parents=True)

        model, _ = build(root)
        section_paths = {p.as_posix() for p in model.sections}

        self.assertIn("parent", section_paths)
        self.assertIn("parent/child", section_paths)
        self.assertTrue((root / "dist/parent/index.html").exists())
        self.assertTrue((root / "dist/parent/child/index.html").exists())


    def test_unknown_template_placeholder_fails_cleanly(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")
        (root / "templates").mkdir()
        (root / "templates/home.html").write_text("<html><body>{{navigtion}}{{content}}</body></html>", encoding="utf-8")

        with self.assertRaises(BuildError):
            validate_project(root)


    def test_assets_directory_symlink_is_rejected(self):
        import os
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")
        target = root / "external-assets"
        target.mkdir()
        (target / "secret.txt").write_text("secret", encoding="utf-8")
        try:
            os.symlink(target, root / "assets", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable on this platform")

        with self.assertRaises(BuildError):
            validate_project(root)


    def test_empty_base_url_override_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")

        with self.assertRaises(BuildError):
            build(root, base_url="")


    def test_unicode_normalization_output_collision_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/café.html", "Composed")
        write_page(root / "content/a/cafe\u0301.html", "Decomposed")

        with self.assertRaises(BuildError):
            build(root)


    def test_generated_file_and_section_directory_collision_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/sitemap.xml/page.html", "Nested")

        with self.assertRaises(BuildError):
            build(root)

    def test_file_and_global_asset_directory_collision_fails(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        (root / "content/assets").write_text("file", encoding="utf-8")
        (root / "assets").mkdir()
        (root / "assets/logo.svg").write_text("<svg></svg>", encoding="utf-8")

        with self.assertRaises(BuildError):
            build(root)



    def test_base_url_rejects_embedded_credentials_and_invalid_port(self):
        temp, root = self.project()
        self.addCleanup(temp.cleanup)
        write_page(root / "content/a/page.html", "Page")

        with self.assertRaises(BuildError):
            build(root, base_url="https://user:secret@example.com/site")
        with self.assertRaises(BuildError):
            build(root, base_url="https://example.com:notaport/site")



if __name__ == "__main__":
    unittest.main()
