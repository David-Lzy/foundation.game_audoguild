"""Read-only integration tests for the installer's Windows path guard."""
from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer only")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def guard(tmp_path_factory):
    path = tmp_path_factory.mktemp("setup-location") / "SetupLocation.exe"
    spec = spec_from_file_location("build_setup", ROOT / "tools" / "build-setup.py")
    build = module_from_spec(spec)
    spec.loader.exec_module(build)
    build.build_location_helper(path)

    def run(candidate, *, existing="", mode="check", limit=140):
        env = {**os.environ, "FTR_SETUP_PATH": str(candidate), "FTR_SETUP_REGISTERED_PATH": str(existing)}
        return subprocess.run([str(path), mode, str(limit)], env=env, timeout=10, check=False,
                              creationflags=subprocess.CREATE_NO_WINDOW).returncode

    return run


def test_allows_custom_folder_under_protected_local_root(guard):
    root = Path(os.environ.get("ProgramW6432") or os.environ["ProgramFiles"])
    candidate = root / ("FTR 安装测试 " + uuid4().hex[:8]) / "Tribute Runner"
    assert guard(candidate) == 0
    assert not candidate.parent.exists()  # The directory page is read-only.
    assert guard(candidate, limit=20) == 10


def test_requires_uninstall_before_changing_registered_path(guard):
    root = Path(os.environ.get("ProgramW6432") or os.environ["ProgramFiles"])
    original = root / ("FTR upgrade " + uuid4().hex)
    assert guard(original, existing=original) == 0
    assert guard(root / "A different folder", existing=original) == 12


def test_rejects_nonempty_unregistered_protected_folder(guard):
    root = Path(os.environ.get("ProgramW6432") or os.environ["ProgramFiles"])
    assert guard(root, mode="prepare") == 14


def test_rejects_user_writable_folder(guard):
    # The current interactive user's profile isn't a trusted owner, regardless of its ACL.
    profile = Path(os.environ["USERPROFILE"])
    assert guard(profile / ("FTR " + uuid4().hex)) != 0


@pytest.mark.parametrize("candidate", [
    r"\\server\share\FTR", r"C:relative", "C:\\", r"C:\Program Files\NUL", r"C:\Program Files\..\FTR",
])
def test_rejects_network_drive_root_and_noncanonical_path(guard, candidate):
    assert guard(candidate) == 10
