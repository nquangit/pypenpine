"""penpine CLI entry point."""
from __future__ import annotations

import argparse
import sys

from penpine.cli.commands import new as new_cmd
from penpine.cli.exceptions import CliError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="penpine",
                                     description="penpine pentesting framework CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="scaffold a new penpine project")
    new.add_argument("name", help="project name (becomes the directory)")
    new.add_argument("--dir", default=".", help="parent directory (default: current)")
    new.add_argument("--no-venv", dest="venv", action="store_false",
                     help="skip virtualenv creation and dependency install")
    new.add_argument("--force", action="store_true",
                     help="scaffold into a non-empty directory")
    new.add_argument("--python", default=None,
                     help="interpreter used to build the virtualenv")
    new.set_defaults(venv=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "new":
            project = new_cmd.run(args.name, target_dir=args.dir,
                                  create_venv=args.venv, force=args.force,
                                  python=args.python)
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
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
