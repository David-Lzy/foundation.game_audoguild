from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from foundation_assistant.win.window import GameWindow, find_game_window

LAUNCH_PATH_ENV = "FOUNDATION_ASSISTANT_LAUNCH_PATH"


def _start_process(path: Path, popen: Callable[..., subprocess.Popen[Any]]) -> subprocess.Popen[Any]:
    argv, cwd = [str(path)], str(path.parent)
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle is None:
        return popen(argv, cwd=cwd)
    # A third-party launcher must not inherit the bundled Python/OCR DLL search path.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_dll_directory = kernel32.SetDllDirectoryW
    set_dll_directory.argtypes = (ctypes.c_wchar_p,)
    set_dll_directory.restype = ctypes.c_int
    if not set_dll_directory(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return popen(argv, cwd=cwd)
    finally:
        if not set_dll_directory(bundle):
            raise ctypes.WinError(ctypes.get_last_error())


def resolve_launch_path(path: str | None, env: Mapping[str, str] | None = None) -> tuple[Path | None, str | None]:
    if path:
        return Path(path).expanduser(), "argument"
    value = (env or os.environ).get(LAUNCH_PATH_ENV)
    if value:
        return Path(value).expanduser(), "environment"
    return None, None


def launch_game(
    *,
    window_title: str,
    window_class: str,
    path: str | None = None,
    wait_seconds: float = 30.0,
    poll_interval: float = 1.0,
    focus: bool = False,
    env: Mapping[str, str] | None = None,
    finder: Callable[[str, str], GameWindow] = find_game_window,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    try:
        window = finder(window_title, window_class)
    except RuntimeError as exc:
        initial_error = str(exc)
    else:
        return _ok_result(
            already_running=True,
            launched=False,
            launch_path=None,
            launch_path_source=None,
            process_id=None,
            window=window,
            attempts=1,
            focus=focus,
        )

    launch_path, launch_path_source = resolve_launch_path(path, env)
    if launch_path is None:
        return {
            "status": "error",
            "failure_reason": "missing_launch_path",
            "already_running": False,
            "launched": False,
            "launch_path": None,
            "launch_path_source": None,
            "process_id": None,
            "attempts": 0,
            "error": f"{initial_error} Pass --path or set {LAUNCH_PATH_ENV}.",
        }

    if not launch_path.exists():
        return {
            "status": "error",
            "failure_reason": "launch_path_not_found",
            "already_running": False,
            "launched": False,
            "launch_path": str(launch_path),
            "launch_path_source": launch_path_source,
            "process_id": None,
            "attempts": 0,
            "error": f"Launch path does not exist: {launch_path}",
        }

    process = _start_process(launch_path, popen)
    deadline = monotonic() + max(0.0, wait_seconds)
    attempts = 0
    last_error = initial_error
    while True:
        attempts += 1
        try:
            window = finder(window_title, window_class)
        except RuntimeError as exc:
            last_error = str(exc)
        else:
            return _ok_result(
                already_running=False,
                launched=True,
                launch_path=launch_path,
                launch_path_source=launch_path_source,
                process_id=getattr(process, "pid", None),
                window=window,
                attempts=attempts,
                focus=focus,
            )

        if monotonic() >= deadline:
            break
        sleep(max(0.0, poll_interval))

    return {
        "status": "error",
        "failure_reason": "window_not_found_after_launch",
        "already_running": False,
        "launched": True,
        "launch_path": str(launch_path),
        "launch_path_source": launch_path_source,
        "process_id": getattr(process, "pid", None),
        "attempts": attempts,
        "error": last_error,
    }


def _ok_result(
    *,
    already_running: bool,
    launched: bool,
    launch_path: Path | None,
    launch_path_source: str | None,
    process_id: int | None,
    window: GameWindow,
    attempts: int,
    focus: bool,
) -> dict[str, Any]:
    focus_record = None
    if focus:
        activated = window.activate()
        focus_record = {"requested": True, "activated": activated, "status": "ok" if activated else "error"}
    return {
        "status": "ok",
        "already_running": already_running,
        "launched": launched,
        "launch_path": str(launch_path) if launch_path is not None else None,
        "launch_path_source": launch_path_source,
        "process_id": process_id,
        "attempts": attempts,
        "window": window,
        "focus": focus_record,
    }
