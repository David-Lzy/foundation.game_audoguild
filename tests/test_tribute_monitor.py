"""Exercise the PowerShell monitor without launching or touching the game."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest


POWERSHELL = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(sys.platform != "win32" or not POWERSHELL, reason="Requires Windows PowerShell")
MONITOR = Path(__file__).resolve().parents[1] / "tools" / "watch-tribute.ps1"


def write_events(path, *events):
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def observe(log, pid, *, stall=2):
    result = subprocess.run([
        POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(MONITOR),
        "-ObservePid", str(pid), "-EventLog", str(log), "-StallSeconds", str(stall), "-PollSeconds", "1",
    ], capture_output=True, timeout=15, check=False)
    lines = result.stdout.decode("utf-8-sig").splitlines()
    assert lines, result.stderr.decode(errors="replace")
    record = json.loads(lines[-1])
    assert record["monitor"] == "done", record
    return result.returncode, record


def test_observer_reports_stop_with_a_pending_rally(tmp_path):
    log = tmp_path / "events.jsonl"
    write_events(log, {"event": "round_submitted"}, {"event": "round_confirmed"},
                 {"event": "round_submitted"}, {"event": "stopped", "code": "runtime_stop", "detail": "input failed"})
    original = log.read_bytes()
    code, record = observe(log, os.getpid())
    assert code == 2
    assert record["status"] == "stopped"
    assert record["pending"] == 1
    assert record["last_event"]["detail"] == "input failed"
    assert log.read_bytes() == original


def test_observer_detects_exit_without_terminal_record(tmp_path):
    log = tmp_path / "events.jsonl"
    write_events(log, {"event": "round_submitted"})
    code, record = observe(log, 2147483647)
    assert code == 2
    assert record["status"] == "exited_without_terminal_event"
    assert record["pending"] == 1 and not record["worker_alive"]


def test_observer_reports_silence_without_stopping_worker(tmp_path):
    log = tmp_path / "events.jsonl"
    write_events(log, {"event": "round_submitted"})
    code, record = observe(log, os.getpid(), stall=1)
    assert code == 3
    assert record["status"] == "stalled"
    assert record["worker_alive"] and record["pending"] == 1


def test_observer_wakes_for_a_new_terminal_record(tmp_path):
    log = tmp_path / "events.jsonl"
    write_events(log, {"event": "round_submitted"}, {"event": "round_confirmed"})

    def finish():
        with log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": "finished", "rallies": 1}) + "\n")

    writer = threading.Timer(1.2, finish)
    writer.start()
    try:
        code, record = observe(log, os.getpid(), stall=5)
    finally:
        writer.join()
    assert code == 0 and record["status"] == "finished"
    assert record["confirmed"] == 1 and record["pending"] == 0
