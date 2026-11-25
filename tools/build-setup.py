"""Build the x64 runtime and compress it into a single offline Windows setup."""
from __future__ import annotations

import argparse
from hashlib import file_digest
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
APP = "FoundationTributeRunner"


def removal_list(payload: Path) -> tuple[str, int]:
    entries = list(payload.rglob("*"))
    files = sorted(path for path in entries if path.is_file())
    folders = sorted((path for path in entries if path.is_dir()), key=lambda path: (-len(path.parts), path))
    size = sum(path.stat().st_size for path in files)

    def installed_path(path: Path) -> str:
        relative = str(path.relative_to(payload)).replace("/", "\\").replace("$", "$$")
        if any(ch in relative for ch in '"\r\n'):
            raise ValueError(f"Invalid package filename: {relative!r}")
        return f'"$INSTDIR\\{relative}"'

    deletes = [f"  Delete {installed_path(path)}" for path in files if path != payload / f"{APP}.exe"]
    deletes.extend(f"  RMDir {installed_path(path)}" for path in folders)
    return "\n".join(deletes) + "\n", (size + 1023) // 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makensis", required=True, type=Path, help="Path to the NSIS makensis.exe")
    args = parser.parse_args()
    if sys.platform != "win32" or struct.calcsize("P") != 8 or os.environ.get("PROCESSOR_ARCHITECTURE") != "AMD64":
        parser.error("Build with an x64 Windows Python.")
    makensis = args.makensis.resolve(strict=True)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        parser.error("Use a numeric major.minor.patch setup version.")

    build = ROOT / "build" / "windows"
    dist = ROOT / "dist"
    payload = dist / APP
    cache = build / "pyinstaller-cache"
    for directory in (dist, payload, build, build / "tribute-runner", cache):
        if directory.resolve() != directory:
            parser.error(f"Refusing to overwrite a redirected path: {directory}")
    env = os.environ.copy()
    env["PYINSTALLER_CONFIG_DIR"] = str(cache)
    conda_bin = Path(sys.base_prefix) / "Library" / "bin"
    if conda_bin.is_dir():
        # With a Conda-based venv, the Python extension DLLs are here, not next to Python.
        env["PATH"] = str(conda_bin) + os.pathsep + env.get("PATH", "")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
                    "--distpath", str(dist), "--workpath", str(build),
                    str(ROOT / "tools" / "tribute-runner.spec")], cwd=ROOT, env=env, check=True)
    output = dist / f"{APP}-{version}-win-x64-setup.exe"
    manifest = build / "remove-files.nsh"
    commands, kib = removal_list(payload)
    manifest.write_text(commands, encoding="utf-8-sig")

    subprocess.run([str(makensis), "/V3", "/WX", f"/DAPP_VERSION={version}", f"/DOUTPUT_EXE={output}",
                    f"/DPAYLOAD_DIR={payload}", f"/DREMOVAL_LIST={manifest}", f"/DPAYLOAD_KIB={kib}",
                    str(ROOT / "tools" / "tribute-setup.nsi")], cwd=ROOT, check=True)
    with output.open("rb") as stream:
        sha256 = file_digest(stream, "sha256").hexdigest()
    (dist / "SHA256SUMS.txt").write_text(f"{sha256}  {output.name}\n", encoding="ascii")
    print(f"{output} ({output.stat().st_size / (1024 * 1024):.1f} MiB)\nSHA-256: {sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
