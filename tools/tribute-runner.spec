# PyInstaller build definition for a normal-privilege, onedir Windows runtime.
from importlib import metadata, util
import json
from pathlib import Path
import sys

from PyInstaller.utils.hooks import copy_metadata


root = Path(SPECPATH).resolve().parent
rapidocr = Path(util.find_spec("rapidocr").origin).parent
data = [
    (str(root / "foundation_assistant/games/foundation/data/templates"), "foundation_assistant/games/foundation/data/templates"),
    (str(root / "LICENSE"), "."),
    (str(root / "NOTICE"), "."),
    *((str(rapidocr / name), "rapidocr") for name in ("config.yaml", "default_models.yaml")),
    *((str(model), "rapidocr/models") for model in sorted((rapidocr / "models").glob("*.onnx"))),
    *copy_metadata("rapidocr"),
]

runtime_distributions = (
    "certifi", "charset-normalizer", "colorama", "colorlog", "flatbuffers", "idna", "mss", "numpy",
    "omegaconf", "onnxruntime", "opencv-python-headless", "packaging", "Pillow", "protobuf", "pyclipper",
    "PyInstaller", "pywin32", "PyYAML", "rapidocr", "requests", "shapely", "six", "tqdm", "urllib3",
)
for name in runtime_distributions:
    dist = metadata.distribution(name)
    for item in dist.files or ():
        if (item.name.lower().startswith(("license", "copying", "notice", "thirdpartynotices"))
                or any(part.lower() == "licenses" for part in item.parts[:-1])):
            source = dist.locate_file(item)
            if source.is_file():
                data.append((str(source), f"ThirdPartyNotices/{name}/{item.parent.as_posix()}"))

base = Path(sys.base_prefix)
for source, dest in [
    (base / "LICENSE.txt", "ThirdPartyNotices/Python"),
    (base / "LICENSE_PYTHON.txt", "ThirdPartyNotices/Python"),
    (base / "tcl/tcl8.6/license.terms", "ThirdPartyNotices/Tcl"),
    (base / "tcl/tk8.6/license.terms", "ThirdPartyNotices/Tk"),
    (base / "Library/lib/tk8.6/license.terms", "ThirdPartyNotices/Tk"),
    *((path, "ThirdPartyNotices/Tcl") for path in base.glob("pkgs/tk-*/info/licenses/tcl*/license.terms")),
]:
    if source.is_file():
        data.append((str(source), dest))

a = Analysis(
    [str(root / "foundation_assistant/desktop.py")],
    pathex=[str(root)],
    datas=data,
    hiddenimports=["rapidocr.main", "onnxruntime", "win32timezone", "pythoncom", "win32com.shell.shell", "win32com.shell.shellcon"],
    excludes=["PIL.AvifImagePlugin", "PIL._avif"],
)
# This workflow uses cv2 for image arrays and matching, not video capture.
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.casefold().startswith("opencv_videoio_ffmpeg")]
# The pinned CPU wheel's Python binding embeds the runtime. The standalone C
# API library is not an import of that binding or used by this application.
if metadata.version("onnxruntime") == "1.32.0":
    a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.casefold() != "onnxruntime.dll"]

# If built on Conda, carry the license texts for Conda libraries that were collected.
bundled = {Path(source).resolve() for _, source, _ in a.binaries}
for record in (base / "conda-meta").glob("*.json"):
    package = json.loads(record.read_text(encoding="utf-8"))
    if not any(base / file in bundled for file in package.get("files", ())):
        continue
    cache = package.get("link", {}).get("source") or base / "pkgs" / record.stem
    licenses = Path(cache) / "info" / "licenses"
    for source in licenses.rglob("*"):
        if source.is_file():
            dest = Path("ThirdPartyNotices") / "conda" / package["name"] / source.relative_to(licenses)
            a.datas.append((str(dest), str(source), "DATA"))

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FoundationTributeRunner", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="FoundationTributeRunner")
