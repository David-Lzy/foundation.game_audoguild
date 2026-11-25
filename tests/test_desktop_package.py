import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from foundation_assistant import cli, desktop, tribute_ui
from foundation_assistant.paths import artifacts_path
from foundation_assistant.win import admin, launch


@pytest.mark.parametrize("frozen", [False, True])
def test_worker_command_and_uac_use_the_same_entry_point(monkeypatch, frozen):
    monkeypatch.setattr(admin.sys, "frozen", frozen, raising=False)
    exe = r"C:\Program Files\Foundation Tribute Runner\FoundationTributeRunner.exe"
    args = ["tribute-cycle", "--captain", "Test Captain", "--total-rallies", "1"]
    expected = args if frozen else ["-m", "foundation_assistant", *args]
    assert admin.application_command(args, exe) == [exe, *expected]
    assert admin.build_elevated_arguments(["launcher", *args], exe) == (exe, subprocess.list2cmdline(expected))


def test_installed_paths_keep_artifacts_per_user(tmp_path):
    install = Path(r"C:\Program Files\Foundation Tribute Runner")
    assert artifacts_path(install, frozen=True, local_app_data=str(tmp_path)) == tmp_path / "FoundationTributeRunner" / "artifacts"
    assert artifacts_path(install, frozen=False, local_app_data=str(tmp_path)) == install / "artifacts"


@pytest.mark.parametrize("args", [
    ["tribute-cycle", "--captain", "Test Captain"],
    ["--profile=foundation", "tribute-loop"],
    ["--require-admin", "tribute-cycle"],
])
def test_packaged_entry_dispatches_worker_flags(monkeypatch, args):
    monkeypatch.setattr(cli, "main", lambda actual: 7 if actual == args else 99)
    assert desktop.main(args) == 7


@pytest.mark.parametrize("args", [[], ["--english"]])
def test_packaged_entry_dispatches_desktop(monkeypatch, args):
    monkeypatch.setattr(tribute_ui, "main", lambda actual: 3 if actual == args else 99)
    assert desktop.main(args) == 3


def test_external_launcher_does_not_inherit_the_bundle_dll_directory(monkeypatch, tmp_path):
    exe = tmp_path / "Launch Game.exe"
    bundle = str(tmp_path / "_internal")
    monkeypatch.setattr(launch.sys, "_MEIPASS", bundle, raising=False)
    calls = []

    def set_dir(path):
        calls.append(path)
        return 1

    def popen(args, *, cwd):
        assert args == [str(exe)]
        assert cwd == str(tmp_path)
        calls.append("launch")
        raise OSError("Launch failed")

    monkeypatch.setattr(launch.ctypes, "WinDLL", lambda *args, **kw: SimpleNamespace(SetDllDirectoryW=set_dir))
    with pytest.raises(OSError, match="Launch failed"):
        launch._start_process(exe, popen)
    assert calls == [None, "launch", bundle]
