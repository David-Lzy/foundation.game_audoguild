from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

SW_HIDE = 0
ELEVATION_ENV = "FOUNDATION_ASSISTANT_ELEVATED_CHILD"
REQUIRE_ADMIN_ENV = "FOUNDATION_ASSISTANT_REQUIRE_ADMIN"


def is_user_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def should_relaunch_as_admin(*, require_admin: bool = False, env: dict[str, str] | None = None) -> bool:
    if sys.platform != "win32":
        return False
    source = os.environ if env is None else env
    if source.get(ELEVATION_ENV) == "1":
        return False
    if is_user_admin():
        return False
    return require_admin or source.get(REQUIRE_ADMIN_ENV) == "1"


def build_elevated_arguments(argv: Sequence[str] | None = None, executable: str | None = None) -> tuple[str, str]:
    current_argv = list(sys.argv if argv is None else argv)
    exe = executable or sys.executable
    if current_argv and Path(current_argv[0]).name == "__main__.py":
        parameters = subprocess.list2cmdline(["-m", "foundation_assistant", *current_argv[1:]])
    elif getattr(sys, "frozen", False):
        parameters = subprocess.list2cmdline(current_argv[1:])
    else:
        parameters = subprocess.list2cmdline(["-m", "foundation_assistant", *current_argv[1:]])
    return exe, parameters


def relaunch_as_admin(argv: Sequence[str] | None = None, cwd: str | None = None) -> int:
    exe, parameters = build_elevated_arguments(argv)
    os.environ[ELEVATION_ENV] = "1"
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        exe,
        parameters,
        cwd or os.getcwd(),
        SW_HIDE,
    )
    if result <= 32:
        raise OSError(f"ShellExecuteW runas failed with code {result}")
    return int(result)


def run_as_admin_and_wait(
    argv: Sequence[str] | None = None,
    *,
    cwd: str | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, object]:
    if sys.platform != "win32":
        raise RuntimeError("Windows UAC elevation is only available on win32.")

    import win32event
    import win32process
    from win32com.shell import shell, shellcon

    exe, parameters = build_elevated_arguments(argv)
    previous = os.environ.get(ELEVATION_ENV)
    os.environ[ELEVATION_ENV] = "1"
    try:
        launched = shell.ShellExecuteEx(
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
            hwnd=None,
            lpVerb="runas",
            lpFile=exe,
            lpParameters=parameters,
            lpDirectory=cwd or os.getcwd(),
            nShow=SW_HIDE,
        )
    finally:
        if previous is None:
            os.environ.pop(ELEVATION_ENV, None)
        else:
            os.environ[ELEVATION_ENV] = previous

    handle = launched["hProcess"]
    timeout_ms = win32event.INFINITE if timeout_seconds is None else int(max(0.0, timeout_seconds) * 1000)
    wait_result = win32event.WaitForSingleObject(handle, timeout_ms)
    if wait_result == win32event.WAIT_TIMEOUT:
        terminated = False
        try:
            win32process.TerminateProcess(handle, 1)
            terminated = True
        except Exception:
            terminated = False
        try:
            handle.Close()
        except Exception:
            pass
        return {
            "status": "timeout",
            "exit_code": None,
            "timeout_seconds": timeout_seconds,
            "terminated": terminated,
            "command": [exe, parameters],
        }

    exit_code = int(win32process.GetExitCodeProcess(handle))
    try:
        handle.Close()
    except Exception:
        pass
    return {
        "status": "ok" if exit_code == 0 else "error",
        "exit_code": exit_code,
        "timeout_seconds": timeout_seconds,
        "command": [exe, parameters],
    }
