from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DATA_DIR = PACKAGE_DIR / "data"
ARTIFACTS_DIR = PROJECT_DIR / "artifacts"
SNAPSHOT_DIR = ARTIFACTS_DIR / "snapshots"
CALIBRATION_DIR = ARTIFACTS_DIR / "calibration"
RUNS_DIR = ARTIFACTS_DIR / "runs"
