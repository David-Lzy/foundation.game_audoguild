import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else PACKAGE_DIR.parent
DATA_DIR = PACKAGE_DIR / "data"


def artifacts_path(project_dir: Path, *, frozen: bool, local_app_data: str | None) -> Path:
    if frozen:
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "FoundationTributeRunner" / "artifacts"
    return project_dir / "artifacts"


ARTIFACTS_DIR = artifacts_path(
    PROJECT_DIR, frozen=bool(getattr(sys, "frozen", False)), local_app_data=os.environ.get("LOCALAPPDATA")
)
SNAPSHOT_DIR = ARTIFACTS_DIR / "snapshots"
CALIBRATION_DIR = ARTIFACTS_DIR / "calibration"
RUNS_DIR = ARTIFACTS_DIR / "runs"
