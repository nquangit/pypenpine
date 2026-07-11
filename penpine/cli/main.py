"""penpine CLI entry point."""

from __future__ import annotations

import argparse
import sys

from penpine.cli.commands import new as new_cmd
from penpine.cli.commands import run as run_cmd
from penpine.cli.exceptions import CliError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="penpine", description="penpine pentesting framework CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="scaffold a new penpine project")
    new.add_argument("name", help="project name (becomes the directory)")
    new.add_argument("--dir", default=".", help="parent directory (default: current)")
    new.add_argument(
        "--no-venv",
        dest="venv",
        action="store_false",
        help="skip virtualenv creation and dependency install",
    )
    new.add_argument("--force", action="store_true", help="scaffold into a non-empty directory")
    new.add_argument("--python", default=None, help="interpreter used to build the virtualenv")
    new.set_defaults(venv=True)

    run_p = sub.add_parser("run", help="run attacks against a request")
    run_p.add_argument("--curl", default=None, help="a 'Copy as cURL' command to attack")
    run_p.add_argument("--request", default=None, help="path to a raw .http request file")
    run_p.add_argument("--url", default=None, help="a URL to attack (bare GET)")
    run_p.add_argument("--target", default=None, help="base URL (scheme://host:port) for --request")
    run_p.add_argument("--attack", default="all", help="comma list of attacks, or 'all' (default)")
    run_p.add_argument("--dry-run", action="store_true", help="list points/payloads; send nothing")
    run_p.add_argument(
        "--fail-on-findings", action="store_true", help="exit 1 if any finding is found"
    )
    run_p.add_argument(
        "--proxy", default=None, help="upstream proxy URL, e.g. http://127.0.0.1:8080"
    )
    run_p.add_argument(
        "--insecure", action="store_true", help="disable TLS certificate verification"
    )
    run_p.add_argument("--concurrency", type=int, default=10, help="max concurrent requests")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "new":
            project = new_cmd.run(
                args.name,
                target_dir=args.dir,
                create_venv=args.venv,
                force=args.force,
                python=args.python,
            )
            print(f"created {project}")
            print("next steps:")
            print(f"  cd {project}")
            if args.venv:
                print("  source .venv/bin/activate")
            else:
                print("  python -m venv .venv && source .venv/bin/activate")
                print("  pip install -r requirements.txt")
            print("  # edit config.py: set TARGET_HOST to an authorized target")
            print("  python main.py")
        elif args.command == "run":
            return run_cmd.run(
                curl=args.curl,
                request_file=args.request,
                url=args.url,
                target=args.target,
                attacks=args.attack,
                dry_run=args.dry_run,
                fail_on_findings=args.fail_on_findings,
                proxy=args.proxy,
                insecure=args.insecure,
                concurrency=args.concurrency,
            )
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
