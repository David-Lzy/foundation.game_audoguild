"""Standalone CLI for the public Tribute Vessel runner."""
from __future__ import annotations

import argparse
import sys

from . import tribute_cycle, tribute_loop
from .win.admin import relaunch_as_admin, should_relaunch_as_admin


def main(argv=None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Foundation: Galactic Frontier Tribute Vessel Runner")
    parser.add_argument("--profile", choices=["foundation"], default="foundation")
    parser.add_argument("--require-admin", action="store_true", help="Request normal Windows UAC elevation.")
    commands = parser.add_subparsers(dest="command", required=True)
    tribute_loop.add_parser(commands)
    tribute_cycle.add_parser(commands)
    args = parser.parse_args(raw)
    if should_relaunch_as_admin(require_admin=args.require_admin):
        relaunch_as_admin([sys.argv[0], *raw])
        return 0
    return int(args.func(args))


def admin_main() -> int:
    return main(["--require-admin", *sys.argv[1:]])
