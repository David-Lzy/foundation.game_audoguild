"""Offline package smoke test. It never looks for or controls the game window."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
import traceback

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from foundation_assistant.games.profiles import get_profile
from foundation_assistant.paths import ARTIFACTS_DIR, PROJECT_DIR
from foundation_assistant.tribute_loop_vision import TextReader, compact
from foundation_assistant.tribute_ui import TributeUI
from foundation_assistant.win.admin import REQUIRE_ADMIN_ENV, application_command


def _check() -> dict:
    from rapidocr import __file__ as rapidocr_file

    model_files = ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx")
    models = Path(rapidocr_file).parent / "models"
    if not all((models / name).is_file() for name in model_files):
        raise RuntimeError("Bundled OCR models are missing.")

    root = tk.Tk()
    try:
        root.withdraw()
        ui = TributeUI(root, captain="Smoke Check")
        choices = root.tk.splitlist(ui.lang_box["values"])
        if tuple(choices) != ("简体中文", "繁體中文", "English"):
            raise RuntimeError(f"Unexpected display languages: {choices}")
        default_language = ui.lang_box.get()
        titles = ("贡品船循环", "貢品船循環", "Tribute Vessel Loop")
        for index, title in enumerate(titles):
            ui.lang_box.current(index)
            ui._language()
            root.update_idletasks()
            if root.title() != title:
                raise RuntimeError(f"Launcher title did not switch to {choices[index]}.")
        default_hunt_retry = ui._settings().hunt_retry_minutes
        if default_hunt_retry != 5 or ui.hunt_spin.instate(["disabled"]):
            raise RuntimeError("Hunt retry was not enabled at the default five-minute interval.")
        ui.hunt_interval.set("2")
        if ui._settings().hunt_retry_minutes != 2:
            raise RuntimeError("The Hunt retry interval did not reach worker settings.")
        ui.hunt_check.invoke()
        if ui._settings().hunt_retry_minutes is not None or not ui.hunt_spin.instate(["disabled"]):
            raise RuntimeError("The Hunt retry checkbox did not turn off retrying.")
    finally:
        root.destroy()

    templates = sorted(get_profile().templates_dir.rglob("*.png"))
    required = {"map_search.png", "map_quick_repair.png", "search_header_en.png", "search_header.png",
                "target_rally.png", "target_rally_en.png", "setup_rally.png", "refill_use.png"}
    if not required.issubset({path.name for path in templates}):
        raise RuntimeError("Game recognition templates are missing.")
    for path in templates:
        with Image.open(path) as template:
            template.verify()

    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    reader = TextReader()
    recognized = {}
    for label, text, font in (("en", "Rally 30", "arialbd.ttf"), ("zh-Hant", "貢品船", "msjhbd.ttc")):
        if label == "zh-Hant" and not (fonts / font).is_file():
            continue  # Not all English Windows installations have this optional system font.
        image = Image.new("RGB", (440, 108), "white")
        ImageDraw.Draw(image).text((22, 14), text, fill="black", font=ImageFont.truetype(str(fonts / font), 56))
        actual = "".join(hit.text for hit in reader.read(np.asarray(image)))
        if compact(actual) != compact(text):
            raise RuntimeError(f"Unexpected {label} OCR result: {actual!r}")
        recognized[label] = actual

    # Test the UI's self-relaunch command with a plan that cannot act on the game.
    env = os.environ.copy()
    env.pop(REQUIRE_ADMIN_ENV, None)
    worker = subprocess.run(application_command([
        "tribute-cycle", "--captain", "Smoke Check", "--level", "3", "--total-rallies", "1", "--strict-count",
    ]), cwd=PROJECT_DIR, env=env, timeout=30, capture_output=True)
    worker.check_returncode()
    if not getattr(sys, "frozen", False) and json.loads(worker.stdout)["mode"] != "plan":
        raise RuntimeError("Worker did not return a dry-run plan.")

    return {"languages": choices, "default_language": default_language, "templates": len(templates),
            "hunt_retry_default_minutes": default_hunt_retry,
            "ocr": recognized, "worker_plan_exit": worker.returncode, "artifacts_dir": str(ARTIFACTS_DIR)}


def write_smoke_report(path: Path) -> int:
    try:
        report = {"ok": True, **_check()}
    except Exception:
        report = {"ok": False, "error": traceback.format_exc()}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return 0 if report["ok"] else 1
