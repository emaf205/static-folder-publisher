from __future__ import annotations

import argparse
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .builder import BuildError, build, clean, validate_project


def _project(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _print_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)


def command_build(project: Path, base_url: str | None = None) -> int:
    try:
        model, warnings = build(project, base_url=base_url)
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_warnings(warnings)
    published = sum(1 for p in model.pages if not p.draft)
    print(f"Built {published} page(s), {len(model.sections)} section(s) -> {model.dist_dir}")
    return 0


def command_validate(project: Path, base_url: str | None = None) -> int:
    try:
        model, warnings = validate_project(project, base_url=base_url)
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_warnings(warnings)
    print(f"Valid: {len(model.pages)} source page(s), {len(model.sections)} section(s).")
    return 0


def command_clean(project: Path) -> int:
    try:
        path = clean(project)
    except OSError as exc:
        print(f"ERROR: Could not clean generated output: {exc}", file=sys.stderr)
        return 1
    print(f"Removed generated output: {path}")
    return 0


def command_serve(project: Path, port: int, base_url: str | None = None) -> int:
    code = command_build(project, base_url=base_url)
    if code:
        return code
    dist = project / "dist"
    handler = partial(SimpleHTTPRequestHandler, directory=str(dist))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        print(f"ERROR: Could not start preview server on port {port}: {exc}", file=sys.stderr)
        return 1
    print(f"Preview: http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


def _add_project_after_command(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project",
        dest="project_after",
        default=None,
        help="Project directory (may also be provided before the command).",
    )


def _add_base_url(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override site.baseUrl for this command without modifying config.json.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publisher", description="Build a static website from folders of finished HTML pages.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--project", default=".", help="Project directory (default: current directory).")
    sub = parser.add_subparsers(dest="command", required=True)

    build_cmd = sub.add_parser("build", help="Validate and build the site into dist/.")
    validate_cmd = sub.add_parser("validate", help="Validate sources and configuration without building.")
    clean_cmd = sub.add_parser("clean", help="Delete dist/.")
    serve = sub.add_parser("serve", help="Build and serve dist/ locally.")
    for command_parser in (build_cmd, validate_cmd, clean_cmd, serve):
        _add_project_after_command(command_parser)
    for command_parser in (build_cmd, validate_cmd, serve):
        _add_base_url(command_parser)
    serve.add_argument("--port", type=int, default=8000, help="Preview port (default: 8000).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project = _project(args.project_after or args.project)

    if args.command == "build":
        return command_build(project, base_url=args.base_url)
    if args.command == "validate":
        return command_validate(project, base_url=args.base_url)
    if args.command == "clean":
        return command_clean(project)
    if args.command == "serve":
        if not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        return command_serve(project, args.port, base_url=args.base_url)
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
