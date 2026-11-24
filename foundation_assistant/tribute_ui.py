"""Small bilingual Windows launcher for the guarded Tribute cycle."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from uuid import uuid4

from foundation_assistant.paths import PROJECT_DIR, RUNS_DIR
from foundation_assistant.tribute_cycle import (
    DEFAULT_BATCH, DEFAULT_TIMEOUT, MAX_BATCH, MAX_TOTAL_RALLIES, MIN_RESULT_TIMEOUT, CycleError, CycleOptions,
)
from foundation_assistant.win.admin import is_user_admin, run_as_admin_and_wait
from foundation_assistant.win.window import ensure_dpi_awareness


TEXT = {
    "title": ("贡品船循环", "Tribute Vessel Loop"),
    "tagline": ("1080p 星图 · 补体力 · 集结 · 核对战报", "1080p star map · refill AP · rally · verify the report"),
    "language": ("启动器语言", "Launcher language"),
    "settings": ("运行参数", "Run settings"),
    "captain": ("游戏昵称", "Player name"),
    "name_hint": ("填准确昵称，不带公会前缀。", "Enter the exact name without its alliance tag."),
    "level": ("贡品船等级", "Vessel level"),
    "batch": ("每批集结次数", "Rallies per batch"),
    "mode": ("运行模式", "Run mode"),
    "timed": ("定时", "Timed"),
    "count": ("按次数", "By count"),
    "continuous": ("持续运行", "Continuous"),
    "hours": ("运行小时数", "Run for (hours)"),
    "total_rallies": ("总集结次数", "Total rallies"),
    "no_limit": ("不限时长和次数", "No time or count limit"),
    "strict_count": ("严格不超次数（可能以满体力停止）", "Strict count limit (final AP may be full)"),
    "timeout": ("结算超时（秒）", "Rally timeout (s)"),
    "repair": ("战后快捷维修（使用已有维修模组）", "Quick repair after each rally (uses owned modules)"),
    "launcher": ("游戏启动器（选填）", "Game launcher (optional)"),
    "browse": ("浏览…", "Browse…"),
    "exe": ("可执行文件", "Executables"),
    "flow": ("每批体力低于 300 才补；本轮新扳手或新胜利战报确认结束，不再固定等待。",
             "Refill only below 300 AP at the start of a batch. A new wrench or victory report ends the wait; no fixed delay."),
    "controls": ("运行时设置窗口保留并更新日志。游戏失去前台时会自动多次尝试拉回，请松开键鼠，别与脚本同时操作。\nF9 正常收尾；F8 急停（不保证体力未满）。到点或到数后，不再补体力。",
                 "This window stays open and shows live logs. The game will be brought back to the front if it loses focus. Release the keyboard and mouse; avoid interacting during automatic clicks. F9 finishes cleanly; F8 stops immediately."),
    "warning": ("游戏支持繁体中文和 English，无需另选。先打完已有集结并回到星图。运行消耗体力和已有药水，不会购买。",
                "The game may use Traditional Chinese or English. Finish existing rallies and return to the star map. Uses AP and owned potions; no purchases."),
    "status": ("运行状态", "Run status"),
    "idle": ("填好参数后，点「开始运行」。", "Fill in the settings, then select Start."),
    "plan": ("预览参数", "Preview settings"),
    "start": ("开始运行", "Start"),
    "open_log": ("打开日志", "Open log"),
    "plan_result": ("计划：{level} 级 · 每批 {batch} 次 · {duration}。没有操作游戏。",
                    "Plan: Lv. {level} · {batch} rallies per batch · {duration}. No game actions taken."),
    "duration_hours": ("{hours} 小时", "{hours} hours"),
    "duration_count": ("完成 {target} 次后收尾（满体力时可能补打）", "start cleanup after {target} rallies (may add rallies if AP is full)"),
    "duration_strict": ("最多 {target} 次（不补打）", "up to {target} rallies (no extra rallies)"),
    "starting_worker": ("正在启动。系统可能要求确认管理员权限。", "Starting. Windows may ask for administrator consent."),
    "running_event": ("运行中：{message}", "Running: {message}"),
    "close_running": ("正在运行。请先按 F9 收尾或 F8 急停，再关闭窗口。", "A run is active. Press F9 to finish or F8 to stop before closing."),
    "worker_error": ("运行未完成或未确认最终体力。请检查日志。", "Run did not finish or final AP was not verified. Check the log."),
    "start_failed": ("没能启动运行进程。", "Could not start the worker."),
    "invalid_captain": ("请输入准确的游戏昵称，不带公会前缀。", "Enter your exact player name without its alliance tag."),
    "invalid_level": ("等级必须是 1–99 的整数。", "Level must be a whole number from 1 to 99."),
    "invalid_batch": ("每批次数必须是 1–10 的整数。", "A batch must contain 1 to 10 rallies."),
    "invalid_hours": ("定时运行请输入大于 0、最多 720 的小时数。", "Enter a timed duration above 0 and no more than 720 hours."),
    "invalid_total_rallies": (f"总集结次数必须是 1–{MAX_TOTAL_RALLIES} 的整数。", f"Enter a whole rally count from 1 to {MAX_TOTAL_RALLIES}."),
    "invalid_timeout": ("结算超时必须是 60–1800 秒。", "Rally timeout must be 60 to 1800 seconds."),
    "invalid_launcher": ("请选择本机存在的游戏启动器 .exe，或留空。", "Choose an existing game launcher .exe, or leave it blank."),
    "unknown_capacity": ("没有读到可确认的 300 体力上限，已停。", "Could not verify a 300 AP cap; stopped."),
    "refill_not_full": ("没核对到补满，已停。", "A full refill could not be verified; stopped."),
    "not_enough_ap": ("体力不够提交集结，已停。", "Not enough AP to submit a rally; stopped."),
    "no_ap_decrease": ("集结结束后没有读到体力下降，已停。", "AP did not decrease after the rally; stopped."),
    "unverified_completion": ("没有核对到本轮结束，已停。", "This rally's completion was not verified; stopped."),
    "cleanup_limit": ("未能在收尾中把体力降到 300 以下，已停。", "Cleanup could not verify AP below 300; stopped."),
    "launch_failed": ("游戏没有启动到可识别的窗口。", "The game did not open in a recognized window."),
    "owner_closed": ("启动界面已关闭，运行停止。", "The launcher was closed; the run stopped."),
    "focus_restoring": ("游戏失去前台，正在等键鼠空闲并尝试拉回。", "Game lost focus; waiting for input to settle and restoring it."),
    "focus_restored": ("游戏已回到前台，将重新截图确认。", "Game back in front; taking a fresh screenshot."),
    "focus_recovery_failed": ("多次尝试仍无法稳定将游戏拉回前台，安全停止。", "Repeated attempts could not keep the game in front; stopped safely."),
    "input_interrupted": ("点击或拖动按下后失去前台，已释放按键，没有重放。", "Focus changed after mouse-down. The button was released and the action was not replayed."),
    "finish_requested": ("已收到 F9，当前操作确认后进入收尾。", "F9 received. Finishing safely after the current action."),
    "interrupted": ("运行被中断，未确认最终体力。", "Run interrupted; final AP was not verified."),
    "runtime_stop": ("触发安全停止，未确认最终体力。", "Safety stop triggered; final AP was not verified."),
    "preparing": ("正在检查游戏窗口。", "Checking the game window."),
    "window_ready": ("游戏画面已确认 1920×1080。", "Confirmed a 1920×1080 game client."),
    "ap_read": ("体力：{ap}/{capacity}", "AP: {ap}/{capacity}"),
    "batch_started": ("第 {batch} 批开始。", "Starting batch {batch}."),
    "refill_started": ("准备补体力：{ap}/{capacity}", "Preparing to refill: {ap}/{capacity} AP"),
    "refilled": ("已核对补满：{ap}/{capacity}", "Refill verified: {ap}/{capacity} AP"),
    "refill_skipped": ("当前 {ap}/{capacity}，不补。", "Already at {ap}/{capacity} AP; no refill."),
    "round_started": ("第 {batch} 批 · 第 {number}/{size} 次 · {level} 级", "Batch {batch} · rally {number}/{size} · Lv. {level}"),
    "round_submitted": ("已点击集结，开始监测结算。", "Rally clicked. Watching for completion."),
    "round_confirmed": ("本轮结束，累计 {rallies} 次。", "Rally completed. Total: {rallies}."),
    "repair_icon": ("新扳手出现，本轮结束，累计 {rallies} 次。", "New wrench detected; rally completed. Total: {rallies}."),
    "victory_mail": ("新胜利战报已确认，累计 {rallies} 次。", "New victory report verified. Total: {rallies}."),
    "repair_done": ("快捷维修提示已清除，累计维修 {repairs} 次。", "Quick-repair prompt cleared. Total repairs: {repairs}."),
    "repair_skipped": ("未见可用的维修按钮，跳过。", "No available repair button; skipped."),
    "batch_done": ("已完成 {batches} 批。", "Completed {batches} batches."),
    "count_reached": ("已完成设定的 {target} 次集结，不再开启新批次。", "Reached {target} rallies; no more batches will start."),
    "count_limit_full_ap": ("已完成 {rallies} 次集结并按次数上限停止，体力仍满：{ap}/{capacity}。没有补打。",
                            "Stopped at the limit of {rallies} rallies. AP is still full: {ap}/{capacity}. No extra rallies."),
    "finishing": ("进入收尾，不再补体力。", "Finishing without refilling."),
    "cleanup_round": ("收尾集结：当前 {ap}/{capacity}。", "Cleanup rally: currently {ap}/{capacity} AP."),
    "finished": ("正常结束：{rallies} 次集结（收尾 {cleanup} 次）· {repairs} 次维修 · 补体力 {refills} 次 · 最终 {ap}/{capacity}。",
                 "Finished: {rallies} rallies ({cleanup} cleanup) · {repairs} repairs · {refills} refills · final AP {ap}/{capacity}."),
}


def tr(lang: int, key: str, **fields: object) -> str:
    return TEXT[key][lang].format(**fields)


def params(*, captain: str, level: str, batch: str, mode: str, hours: str, timeout: str, launch: str,
           repair_after_rally: bool = True, total_rallies: str = "", strict_count: bool = False) -> CycleOptions:
    numbers: list[int] = []
    for name, value in (("level", level), ("batch", batch), ("timeout", timeout)):
        try:
            numbers.append(int(value))
        except ValueError as exc:
            raise CycleError(f"invalid_{name}") from exc
    try:
        duration = float(hours) if mode == "timed" else None
    except ValueError as exc:
        raise CycleError("invalid_hours") from exc
    try:
        total = int(total_rallies) if mode == "count" else None
    except ValueError as exc:
        raise CycleError("invalid_total_rallies") from exc
    return CycleOptions(captain, numbers[0], numbers[1], duration, numbers[2],
                        Path(launch.strip()) if launch.strip() else None, repair_after_rally,
                        total_rallies=total, strict_count=strict_count and total is not None)


def _worker(args: list[str], done: SimpleQueue) -> None:
    try:
        if is_user_admin():
            proc = subprocess.run([sys.executable, "-m", "foundation_assistant", *args], cwd=PROJECT_DIR,
                                  creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            done.put((proc.returncode, ""))
        else:
            import pythoncom

            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED | pythoncom.COINIT_DISABLE_OLE1DDE)
            try:
                result = run_as_admin_and_wait(["foundation_assistant", *args], cwd=str(PROJECT_DIR))
            finally:
                pythoncom.CoUninitialize()
            done.put((result.get("exit_code"), ""))
    except Exception as exc:
        done.put((None, str(exc)))


class TributeUI:
    def __init__(self, root: tk.Tk, *, captain: str = "", english: bool = False) -> None:
        self.root = root
        self.lang = int(english)
        self.bindings = []
        self.status = ("idle", {})
        self.record: Path | None = None
        self.events: list[dict] = []
        self.offset = 0
        self.running = False
        self.done = SimpleQueue()
        self.captain = tk.StringVar(value=captain)
        self.level = tk.StringVar(value="3")
        self.batch = tk.StringVar(value=str(DEFAULT_BATCH))
        self.mode = tk.StringVar(value="timed")
        self.hours = tk.StringVar(value="1")
        self.total_rallies = tk.StringVar(value=str(DEFAULT_BATCH))
        self.strict_count = tk.BooleanVar(value=False)
        self.timeout = tk.StringVar(value=str(DEFAULT_TIMEOUT))
        self.launch = tk.StringVar()
        self.repair_after_rally = tk.BooleanVar(value=True)
        self._build()
        self._translate()

    def local(self, widget, key: str):
        self.bindings.append((widget, key))
        return widget

    def _build(self) -> None:
        root = self.root
        root.geometry("870x928")
        root.minsize(810, 835)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.configure(background="#eaf0f8")
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        font = "Microsoft YaHei UI"
        style.configure("TFrame", background="#eaf0f8")
        style.configure("TLabelframe", background="#eaf0f8", bordercolor="#b4c2d3")
        style.configure("TLabelframe.Label", background="#eaf0f8", foreground="#122b46", font=(font, 11, "bold"))
        style.configure("TLabel", background="#eaf0f8", foreground="#1e3755", font=(font, 10))
        style.configure("TRadiobutton", background="#eaf0f8", foreground="#1e3755", font=(font, 10))
        style.configure("TCheckbutton", background="#eaf0f8", foreground="#1e3755", font=(font, 10))
        style.configure("TButton", padding=(11, 6), background="#f5f9ff", foreground="#16334e", font=(font, 10))
        style.map("TButton", background=[("active", "#e1edfb"), ("disabled", "#dce4ee")])
        style.configure("Go.TButton", background="#155daa", foreground="white", font=(font, 10, "bold"))
        style.map("Go.TButton", background=[("active", "#104782"), ("disabled", "#5b6d80")])
        style.configure("Tip.TLabel", foreground="#3f526b", font=(font, 9))
        style.configure("Focus.TLabel", foreground="#173d65", font=(font, 9, "bold"))
        style.configure("Status.TLabel", foreground="#113f73", font=(font, 10, "bold"))

        hero = tk.Frame(root, background="#142941", padx=24, pady=13)
        hero.grid(sticky="ew")
        hero.columnconfigure(0, weight=1)
        self.local(tk.Label(hero, background="#142941", foreground="#fff", font=(font, 20, "bold")), "title").grid(row=0, column=0, sticky="w")
        self.local(tk.Label(hero, background="#142941", foreground="#c6daf1", font=(font, 10)), "tagline").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.local(tk.Label(hero, background="#142941", foreground="#c6daf1", font=(font, 9)), "language").grid(row=0, column=1, sticky="w", padx=(14, 0))
        self.lang_box = ttk.Combobox(hero, values=("简体中文", "English"), state="readonly", width=11)
        self.lang_box.current(self.lang)
        self.lang_box.grid(row=1, column=1, sticky="e", padx=(14, 0))
        self.lang_box.bind("<<ComboboxSelected>>", self._language)

        content = ttk.Frame(root, padding=(20, 13, 20, 11))
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(4, weight=1)
        form = self.local(ttk.LabelFrame(content, padding=(14, 7, 14, 10)), "settings")
        self.form = form
        form.grid(row=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        def label(row, col, key):
            self.local(ttk.Label(form, anchor="w"), key).grid(row=row, column=col, sticky="w", padx=(0, 10), pady=5)

        label(0, 0, "captain")
        self.name_entry = ttk.Entry(form, textvariable=self.captain)
        self.name_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=5)
        self.local(ttk.Label(form, style="Tip.TLabel"), "name_hint").grid(row=1, column=1, columnspan=3, sticky="w")
        label(2, 0, "level")
        ttk.Spinbox(form, from_=1, to=99, textvariable=self.level, width=7).grid(row=2, column=1, sticky="w", pady=5)
        label(2, 2, "batch")
        ttk.Spinbox(form, from_=1, to=MAX_BATCH, textvariable=self.batch, width=7).grid(row=2, column=3, sticky="w", pady=5)
        label(3, 0, "mode")
        modes = ttk.Frame(form)
        modes.grid(row=3, column=1, columnspan=3, sticky="w")
        for col, key in enumerate(("timed", "count", "continuous")):
            self.local(ttk.Radiobutton(modes, value=key, variable=self.mode, command=self._change_mode), key).grid(row=0, column=col, padx=(0, 16), pady=4)
        self.limit_label = ttk.Label(form, anchor="w")
        self.limit_label.grid(row=4, column=0, sticky="w", padx=(0, 10), pady=5)
        self.limit_entry = ttk.Entry(form, width=10)
        self.limit_entry.grid(row=4, column=1, sticky="w", pady=5)
        label(4, 2, "timeout")
        ttk.Spinbox(form, from_=MIN_RESULT_TIMEOUT, to=1800, increment=15, textvariable=self.timeout, width=7).grid(row=4, column=3, sticky="w", pady=5)
        label(5, 0, "launcher")
        ttk.Entry(form, textvariable=self.launch).grid(row=5, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=5)
        self.local(ttk.Button(form, command=self._browse), "browse").grid(row=5, column=3, sticky="e")
        self.local(ttk.Checkbutton(form, variable=self.repair_after_rally), "repair").grid(row=6, column=1, columnspan=3, sticky="w", pady=(4, 1))
        self.count_check = self.local(ttk.Checkbutton(form, variable=self.strict_count), "strict_count")
        self.count_check.grid(row=7, column=1, columnspan=3, sticky="w", pady=(3, 1))

        for row, key in enumerate(("flow", "controls", "warning"), start=1):
            style_name = "Focus.TLabel" if key == "controls" else "Tip.TLabel"
            self.local(ttk.Label(content, style=style_name, wraplength=733, justify="left"), key).grid(row=row, sticky="ew", pady=(7 if row == 1 else 3, 0))

        status = self.local(ttk.LabelFrame(content, padding=(10, 5, 10, 7)), "status")
        status.grid(row=4, sticky="nsew", pady=(9, 0))
        status.columnconfigure(0, weight=1)
        status.rowconfigure(1, weight=1)
        self.status_text = ttk.Label(status, wraplength=706, style="Status.TLabel")
        self.status_text.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 3))
        self.log = tk.Text(status, height=4, wrap="word", bg="white", fg="#1e3755", font=(font, 9), relief="flat", padx=7, pady=4, state="disabled")
        self.log.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(status, orient="vertical", command=self.log.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        bar = ttk.Frame(root, padding=(20, 0, 20, 14))
        bar.grid(row=2, sticky="ew")
        bar.columnconfigure(1, weight=1)
        self.log_button = self.local(ttk.Button(bar, command=self._open_log, state="disabled"), "open_log")
        self.log_button.grid(row=0, column=0, sticky="w")
        self.plan_button = self.local(ttk.Button(bar, command=self.validate), "plan")
        self.plan_button.grid(row=0, column=2, padx=(0, 8))
        self.run_button = self.local(ttk.Button(bar, style="Go.TButton", command=self.run), "start")
        self.run_button.grid(row=0, column=3)

        content.bind("<Configure>", lambda event: self._wrap(event.width))
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _wrap(self, width: int) -> None:
        for widget, key in self.bindings:
            if key in {"flow", "controls", "warning"}:
                widget.configure(wraplength=max(400, width - 40))
        self.status_text.configure(wraplength=max(400, width - 60))

    def _language(self, _event=None) -> None:
        self.lang = max(self.lang_box.current(), 0)
        self._translate()

    def _translate(self) -> None:
        self.root.title(tr(self.lang, "title"))
        for widget, key in self.bindings:
            widget.configure(text=tr(self.lang, key))
        self._change_mode()
        self._render_status()
        self._render_log()

    def _change_mode(self) -> None:
        mode = self.mode.get()
        self.limit_label.configure(text=tr(self.lang, {"count": "total_rallies", "timed": "hours"}.get(mode, "no_limit")))
        self.limit_entry.configure(textvariable=self.total_rallies if mode == "count" else self.hours,
                                   state="normal" if not self.running and mode in {"timed", "count"} else "disabled")
        if mode == "continuous":
            self.limit_entry.grid_remove()
        else:
            self.limit_entry.grid()
        if mode == "count":
            self.count_check.grid()
        else:
            self.count_check.grid_remove()

    def _run_controls(self) -> None:
        state = ["disabled" if self.running else "!disabled"]

        def update(parent):
            for child in parent.winfo_children():
                if isinstance(child, (ttk.Entry, ttk.Spinbox, ttk.Radiobutton, ttk.Checkbutton, ttk.Button)):
                    child.state(state)
                update(child)

        update(self.form)
        self.plan_button.state(state)
        self.run_button.state(state)
        self._change_mode()

    def _browse(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title=tr(self.lang, "launcher"), filetypes=[(tr(self.lang, "exe"), "*.exe")])
        if path:
            self.launch.set(path)

    def _settings(self) -> CycleOptions:
        return params(captain=self.captain.get(), level=self.level.get(), batch=self.batch.get(), mode=self.mode.get(),
                      hours=self.hours.get(), timeout=self.timeout.get(), launch=self.launch.get(),
                      repair_after_rally=self.repair_after_rally.get(), total_rallies=self.total_rallies.get(),
                      strict_count=self.strict_count.get())

    def _status(self, key: str, **fields: object) -> None:
        self.status = (key, fields)
        self._render_status()

    def _render_status(self) -> None:
        key, stored = self.status
        fields = dict(stored)
        if key == "plan_result":
            hours = fields.pop("hours")
            total, strict = fields.pop("total_rallies"), fields.pop("strict_count")
            if total is not None:
                fields["duration"] = tr(self.lang, "duration_strict" if strict else "duration_count", target=total)
            else:
                fields["duration"] = tr(self.lang, "continuous") if hours is None else tr(self.lang, "duration_hours", hours=f"{hours:g}")
        if key == "running_event":
            fields["message"] = self._event_text(fields.pop("row")) or tr(self.lang, "preparing")
        self.status_text.configure(text=tr(self.lang, key, **fields))

    def validate(self) -> None:
        try:
            cfg = self._settings()
        except CycleError as exc:
            self._status(exc.code)
        else:
            self._status("plan_result", level=cfg.level, batch=cfg.batch_size, hours=cfg.hours,
                         total_rallies=cfg.total_rallies, strict_count=cfg.strict_count)

    def run(self) -> None:
        if self.running:
            return
        try:
            cfg = self._settings()
        except CycleError as exc:
            self._status(exc.code)
            return
        path = RUNS_DIR / f"tribute-cycle-{uuid4().hex[:12]}" / "events.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            self._status("start_failed")
            self.events = [{"event": "detail", "detail": str(exc)}]
            self._render_log()
            return
        self.record, self.offset, self.events = path, 0, []
        self.running = True
        self._run_controls()
        self.log_button.configure(state="disabled")
        self._status("starting_worker")
        self._render_log()
        args = ["tribute-cycle", "--execute", "--event-log", str(path), "--owner-pid", str(os.getpid()), *cfg.arguments()]
        # This window remains open and never goes topmost. The worker is
        # responsible for restoring game focus before it uses the desktop.
        threading.Thread(target=_worker, args=(args, self.done), daemon=True, name="tribute-runtime").start()
        self.root.after(600, self._poll)

    def _read_events(self) -> bool:
        if not self.record or not self.record.is_file():
            return False
        added = False
        with self.record.open("rb") as stream:
            stream.seek(self.offset)
            for line in stream:
                if not line.endswith(b"\n"):
                    break
                self.offset += len(line)
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(event, dict):
                    self.events.append(event)
                    added = True
        self.events = self.events[-180:]
        return added

    def _event_text(self, row: dict) -> str:
        kind = row.get("event")
        key = row.get("code", "runtime_stop") if kind == "stopped" else kind
        if kind == "round_confirmed" and row.get("completion") in ("repair_icon", "victory_mail"):
            key = row["completion"]
        if kind == "finished":
            row = {"repairs": 0, "cleanup": 0} | row
        if isinstance(key, str) and key in TEXT:
            try:
                return tr(self.lang, key, **row)
            except (KeyError, ValueError, TypeError):
                pass
        return ""

    def _render_log(self) -> None:
        lines = []
        for row in self.events:
            kind = row.get("event")
            message = self._event_text(row)
            if message:
                lines.append(message)
            if row.get("detail") and (kind == "stopped" or self.lang == 0):
                lines.append(str(row["detail"]))
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", "\n".join(lines))
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self) -> None:
        try:
            updated = self._read_events()
        except OSError:
            updated = False
        try:
            rc, detail = self.done.get_nowait()
        except Empty:
            if updated:
                row = next((e for e in reversed(self.events) if self._event_text(e)), None)
                if row is not None:
                    self._status("running_event", row=row)
                self._render_log()
            self.root.after(800, self._poll)
            return
        try:
            self._read_events()
        except OSError:
            pass
        self.running = False
        self._run_controls()
        final = next((r for r in reversed(self.events) if r.get("event") in {"finished", "stopped"}), None)
        if rc == 0 and final and final["event"] == "finished":
            self._status("finished", **({"repairs": 0, "cleanup": 0} | final))
        elif final and final["event"] == "stopped" and final.get("code") in TEXT:
            self._status(final["code"], **final)
        else:
            self._status("start_failed" if rc is None else "worker_error")
        if detail:
            self.events.append({"event": "stopped", "code": "start_failed", "detail": detail})
        if self.record and self.record.exists():
            self.log_button.configure(state="normal")
        self._render_log()

    def _open_log(self) -> None:
        if self.record and self.record.is_file():
            try:
                os.startfile(str(self.record.parent))
            except OSError:
                self._status("worker_error")

    def _close(self) -> None:
        if not self.running:
            self.root.destroy()
        else:
            self._status("close_running")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bilingual Tribute Vessel settings window.")
    parser.add_argument("--captain", default="", help="Optional initial player name.")
    parser.add_argument("--english", action="store_true", help="Open the UI in English.")
    args = parser.parse_args(argv)
    ensure_dpi_awareness()
    root = tk.Tk()
    ui = TributeUI(root, captain=args.captain, english=args.english)
    ui.name_entry.focus_set()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
