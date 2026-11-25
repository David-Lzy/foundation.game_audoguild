"""Entry point shared by the packaged desktop launcher and its worker process."""
from __future__ import annotations

import argparse
import multiprocessing
import os
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--smoke-report"]:
        from foundation_assistant.package_check import write_smoke_report

        parser = argparse.ArgumentParser(description="Check the desktop package without touching the game.")
        parser.add_argument("--smoke-report", required=True, type=Path)
        return write_smoke_report(parser.parse_args(args).smoke_report)
    if args and (args[0] in {"tribute-cycle", "tribute-loop", "--profile", "--require-admin"}
                 or args[0].startswith("--profile=")):
        from foundation_assistant.cli import main as worker_main

        return worker_main(args)

    from foundation_assistant.tribute_ui import main as launcher_main

    return launcher_main(args)


if __name__ == "__main__":
    # A windowed bundle has no console. Third-party loggers still expect streams.
    for stream in ("stdout", "stderr"):
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, "w", encoding="utf-8"))
    multiprocessing.freeze_support()
    raise SystemExit(main())
