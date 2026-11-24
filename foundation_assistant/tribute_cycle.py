"""Timed, counted, or continuous AP refill / Tribute Vessel batches."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from typing import Callable, Protocol

import win32api
import win32con
import win32event
import win32gui

from foundation_assistant.games import GameProfile, get_profile
from foundation_assistant.tribute_loop import AP_COST, Desktop, RetryBeforeInput, Stop, TributeLoop, prepare_window, single_instance
from foundation_assistant.tribute_loop_vision import Frame, Point, TextReader
from foundation_assistant.vision.screenshot import capture_window
from foundation_assistant.win.launch import launch_game
from foundation_assistant.win.window import GameWindow, find_game_window


CAPACITY = 300
DEFAULT_BATCH = 8
DEFAULT_TIMEOUT = 480
MIN_RESULT_TIMEOUT = 60
MAX_BATCH = CAPACITY // AP_COST
MAX_TOTAL_RALLIES = 10_000
FOCUS_TIMEOUT = 30
FOCUS_RETRY_DELAY = 0.55
FOCUS_SETTLE = 0.16
FOCUS_IDLE_MS = 450
INPUT_HELD_KEYS = (win32con.VK_LBUTTON, win32con.VK_RBUTTON, win32con.VK_MBUTTON,
                   win32con.VK_SHIFT, win32con.VK_CONTROL, win32con.VK_MENU, 0x5B, 0x5C)
Event = Callable[..., None]
AP = tuple[int, int]


class CycleError(Stop):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(detail or code)


@dataclass(frozen=True)
class CycleOptions:
    captain: str
    level: int = 3
    batch_size: int = DEFAULT_BATCH
    hours: float | None = None
    result_timeout: int = DEFAULT_TIMEOUT
    launch_path: Path | None = None
    repair_after_rally: bool = True
    total_rallies: int | None = None
    strict_count: bool = False

    def __post_init__(self) -> None:
        nickname = self.captain.strip()
        if not (1 <= len(nickname) <= 26 and any(char.isalnum() for char in nickname)) or nickname.startswith(("[", "【")):
            raise CycleError("invalid_captain")
        object.__setattr__(self, "captain", nickname)
        if not 1 <= self.level <= 99:
            raise CycleError("invalid_level")
        if not 1 <= self.batch_size <= MAX_BATCH:
            raise CycleError("invalid_batch")
        if self.hours is not None and (not math.isfinite(self.hours) or not 0 < self.hours <= 720):
            raise CycleError("invalid_hours")
        if self.total_rallies is not None and (type(self.total_rallies) is not int or not 1 <= self.total_rallies <= MAX_TOTAL_RALLIES):
            raise CycleError("invalid_total_rallies")
        if self.hours is not None and self.total_rallies is not None:
            raise CycleError("conflicting_stop_modes")
        if self.strict_count and self.total_rallies is None:
            raise CycleError("strict_count_requires_total")
        if not MIN_RESULT_TIMEOUT <= self.result_timeout <= 1800:
            raise CycleError("invalid_timeout")
        if self.launch_path is not None:
            path = self.launch_path.expanduser()
            if not path.is_absolute() or path.suffix.casefold() != ".exe" or not path.is_file():
                raise CycleError("invalid_launcher")
            object.__setattr__(self, "launch_path", path)

    def arguments(self) -> list[str]:
        args = [f"--captain={self.captain}", "--level", str(self.level), "--batch-size", str(self.batch_size),
                "--result-timeout", str(self.result_timeout)]
        if self.hours is not None:
            args.extend(("--hours", str(self.hours)))
        if self.total_rallies is not None:
            args.extend(("--total-rallies", str(self.total_rallies)))
        if self.strict_count:
            args.append("--strict-count")
        if self.launch_path is not None:
            args.extend(("--launch-path", str(self.launch_path)))
        if not self.repair_after_rally:
            args.append("--no-repair-after-rally")
        return args


class CycleGame(Protocol):
    def read_action_points(self) -> AP: ...
    def refill(self, allow_use: Callable[[], bool]) -> bool: ...
    def rally(self, options: CycleOptions) -> str: ...
    def repair(self) -> bool: ...


@dataclass(frozen=True)
class CycleSummary:
    reason: str
    ap: int
    capacity: int
    rallies: int
    batches: int
    refills: int
    cleanup: int
    elapsed_seconds: float
    repairs: int = 0


class CycleRunner:
    def __init__(self, game: CycleGame, options: CycleOptions, *, emit: Event,
                 finish_requested: Callable[[], bool], clock: Callable[[], float] = time.monotonic) -> None:
        self.game, self.options, self.emit = game, options, emit
        self.finish_requested, self.clock = finish_requested, clock
        self.started = 0.0
        self.rallies = self.batches = self.refills = self.cleanup = self.repairs = 0

    def _reason(self) -> str | None:
        if self.options.total_rallies is not None and self.rallies >= self.options.total_rallies:
            return "count_limit"
        if self.finish_requested():
            return "requested"
        if self.options.hours is not None and self.clock() - self.started >= self.options.hours * 3600:
            return "time_limit"
        return None

    def _points(self) -> int:
        points, cap = self.game.read_action_points()
        if cap != CAPACITY or not 0 <= points <= 1000:
            raise CycleError("unknown_capacity", f"AP: {points}/{cap}")
        self.emit("ap_read", ap=points, capacity=cap)
        return points

    def _rally(self, ap: int, *, number: int, cleanup: bool = False, batch_size: int | None = None) -> int:
        if ap < AP_COST:
            raise CycleError("not_enough_ap", f"AP: {ap}/{CAPACITY}")
        self.emit("cleanup_round" if cleanup else "round_started", batch=self.batches + 1, number=number,
                  size=batch_size or self.options.batch_size, level=self.options.level, ap=ap, capacity=CAPACITY)
        source = self.game.rally(self.options)
        if source not in {"repair_icon", "victory_mail"}:
            raise CycleError("unverified_completion")
        self.rallies += 1
        if cleanup:
            self.cleanup += 1
        self.emit("round_confirmed", rallies=self.rallies, completion=source)
        if self.options.repair_after_rally:
            repaired = self.game.repair()
            if repaired:
                self.repairs += 1
            self.emit("repair_done" if repaired else "repair_skipped", repairs=self.repairs)
        afterward = self._points()
        if afterward >= ap:
            raise CycleError("no_ap_decrease", f"AP: {ap} → {afterward}/{CAPACITY}")
        return afterward

    def _finish(self, reason: str) -> CycleSummary:
        if reason == "count_limit":
            self.emit("count_reached", target=self.options.total_rallies)
        self.emit("finishing", reason=reason)
        ap = self._points()
        # A batch refill can go above 300. Continue only until the live readback
        # is below the cap, not until a new batch completes. Abort if the AP
        # does not fall or a match runs beyond a bounded finishing allowance.
        allowance = max(0, math.ceil((ap - CAPACITY + 1) / 20))
        limit = self.options.total_rallies if self.options.strict_count else None
        while ap >= CAPACITY and self.cleanup < allowance and (limit is None or self.rallies < limit):
            ap = self._rally(ap, number=self.cleanup + 1, cleanup=True)
        if ap >= CAPACITY and (limit is None or self.rallies < limit):
            raise CycleError("cleanup_limit", f"AP: {ap}/{CAPACITY}")
        return CycleSummary(reason, ap, CAPACITY, self.rallies, self.batches, self.refills,
                            self.cleanup, round(self.clock() - self.started, 1), self.repairs)

    def run(self) -> CycleSummary:
        self.started = self.clock()
        ap = self._points()
        while True:
            if reason := self._reason():
                return self._finish(reason)
            batch = self.batches + 1
            size = self.options.batch_size
            if self.options.total_rallies is not None:
                size = min(size, self.options.total_rallies - self.rallies)
            self.emit("batch_started", batch=batch, size=size)
            if ap < CAPACITY:
                self.emit("refill_started", ap=ap, capacity=CAPACITY)
                used = self.game.refill(lambda: self._reason() is None)
                if used:
                    self.refills += 1
                ap = self._points()
                if used:
                    self.emit("refilled", ap=ap, capacity=CAPACITY, refills=self.refills)
                if reason := self._reason():
                    return self._finish(reason)
                if ap < CAPACITY:
                    raise CycleError("refill_not_full", f"AP: {ap}/{CAPACITY}")
            else:
                self.emit("refill_skipped", ap=ap, capacity=CAPACITY)
            for number in range(1, size + 1):
                if reason := self._reason():
                    return self._finish(reason)
                ap = self._rally(ap, number=number, batch_size=size)
            if size == self.options.batch_size:
                self.batches += 1
                self.emit("batch_done", batches=self.batches, rallies=self.rallies, ap=ap, capacity=CAPACITY)


class CycleDesktop(Desktop):
    """Recover focus for observation, but never reuse a point across focus loss."""

    def __init__(self, profile: GameProfile, window: GameWindow, reader: TextReader, owner=None,
                 *, emit: Event = lambda *_a, **_kw: None) -> None:
        self.owner = owner
        self.emit = emit
        self.finish_requested = False
        self._pressed = False
        self._observed_input: tuple[int, Point] | None = None
        super().__init__(profile, window, reader)

    def _start_window(self) -> None:
        self.check()

    def _controls(self) -> None:
        if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
            raise Stop("收到 F8 急停。")
        if self.owner is not None and win32event.WaitForSingleObject(self.owner, 0) != win32event.WAIT_TIMEOUT:
            raise CycleError("owner_closed")
        if not self.finish_requested and win32api.GetAsyncKeyState(win32con.VK_F9) & 0x8000:
            self.finish_requested = True
            self.emit("finish_requested")

    def _foreground(self) -> bool:
        return win32gui.GetForegroundWindow() == self.window.hwnd and not win32gui.IsIconic(self.window.hwnd)

    def _guard_window(self) -> None:
        self._controls()
        current = find_game_window(self.profile.window_title, self.profile.window_class)
        if (current.hwnd, current.process_id) != (self.window.hwnd, self.window.process_id):
            raise Stop("游戏窗口或进程已变化，已停止。")
        # A minimized window can report a special screen position. Validate
        # the exact prepared rect once it is restored, before any captures.
        if not win32gui.IsIconic(current.hwnd) and current.client_rect != self.window.client_rect:
            raise Stop("游戏窗口位置或尺寸已变化，已停止。")

    @staticmethod
    def _held() -> bool:
        return any(win32api.GetAsyncKeyState(key) & 0x8000 for key in INPUT_HELD_KEYS)

    def _idle(self) -> bool:
        delta = (win32api.GetTickCount() - win32api.GetLastInputInfo()) & 0xFFFF_FFFF
        return FOCUS_IDLE_MS <= delta < 0x8000_0000 and not self._held()

    @staticmethod
    def _input_stamp() -> tuple[int, Point]:
        return win32api.GetLastInputInfo(), win32api.GetCursorPos()

    def _pause_recovery(self, duration: float) -> None:
        deadline = time.monotonic() + duration
        while (remaining := deadline - time.monotonic()) > 0:
            self._controls()
            time.sleep(min(0.1, remaining))

    def _restore_foreground(self) -> None:
        self.emit("focus_restoring")
        deadline = time.monotonic() + FOCUS_TIMEOUT
        attempts = 0
        while time.monotonic() < deadline:
            self._guard_window()
            if not self._foreground() and self._idle():
                self._controls()
                self.window.activate()
                attempts += 1
            if self._foreground():
                self._pause_recovery(FOCUS_SETTLE)
                if self._foreground():
                    self._guard_window()
                    self.emit("focus_restored", attempts=attempts)
                    return
            self._pause_recovery(FOCUS_RETRY_DELAY)
        raise CycleError("focus_recovery_failed", f"{attempts} foreground attempts")

    def check(self) -> None:
        self._guard_window()
        if not self._foreground():
            self._observed_input = None
            if self._pressed:
                raise CycleError("input_interrupted", "Foreground switched after mouse-down; the gesture was not replayed.")
            self._restore_foreground()

    def frame(self) -> Frame:
        for _ in range(3):
            self.check()
            stamp = self._input_stamp()
            image = capture_window(self.window)
            self._guard_window()
            if self._foreground():
                self._observed_input = stamp if stamp == self._input_stamp() else None
                return Frame(image, self.profile.templates_dir, self.reader)
            self._observed_input = None  # Never return a desktop image captured across a focus change.
        raise CycleError("focus_recovery_failed", "Foreground changed during three captures.")

    def _before_press(self, point: Point) -> Point:
        self._guard_window()
        if not self._foreground() or self._held():
            self._observed_input = None
            raise RetryBeforeInput("Foreground or a held key changed before mouse-down.")
        try:
            return self._screen_point(point)
        except Stop:
            if not self._foreground():
                self._observed_input = None
                raise RetryBeforeInput("Foreground changed while verifying the target point.") from None
            raise

    def _mouse_start(self, point: Point) -> None:
        location = self._before_press(point)
        if self._observed_input is None or self._observed_input != self._input_stamp():
            raise RetryBeforeInput("User input changed since the screenshot.")
        self._observed_input = None
        self.input.move(*location)
        self._pause_recovery(0.04)
        target = self._before_press(point)
        if math.dist(win32api.GetCursorPos(), target) > 3 or not self._foreground() or self._held():
            raise RetryBeforeInput("Cursor moved before mouse-down.")
        self._pressed = True
        self.input.mouse_down()

    def click(self, point: Point) -> None:
        try:
            super().click(point)
        finally:
            self._pressed = False

    def drag(self, start: Point, end: Point) -> None:
        try:
            super().drag(start, end)
        finally:
            self._pressed = False


class LiveCycleGame:
    def __init__(self, loop: TributeLoop, emit: Event) -> None:
        self.loop, self.emit = loop, emit

    def read_action_points(self) -> AP:
        return self.loop.read_action_points()

    def refill(self, allow_use: Callable[[], bool]) -> bool:
        return self.loop.refill(preview=False, allow_use=allow_use)

    def rally(self, options: CycleOptions) -> str:
        before = self.loop.wait("提交前的星图维修提示基线", Frame.repair_view)
        sent = self.loop.start(options.level, preview=False)
        if sent is None:
            raise CycleError("not_submitted")
        self.emit("round_submitted", repair_already_visible=before.button is not None)
        return self.loop.wait_battle_end(options.captain, options.level, sent, options.result_timeout,
                                         repair_already_visible=before.button is not None)

    def repair(self) -> bool:
        return self.loop.repair_fleet()


@contextmanager
def _owner_process(pid: int | None):
    handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid) if pid is not None else None
    try:
        yield handle
    finally:
        if handle is not None:
            handle.Close()


def _live(options: CycleOptions, profile_name: str, emit: Event, owner_pid: int | None) -> CycleSummary:
    profile = get_profile(profile_name)
    with _owner_process(owner_pid) as owner, single_instance():
        if options.launch_path is not None:
            result = launch_game(window_title=profile.window_title, window_class=profile.window_class,
                                 path=str(options.launch_path), wait_seconds=90)
            if result.get("status") != "ok":
                raise CycleError("launch_failed", str(result.get("error", "")))
        window = prepare_window(profile)
        emit("window_ready")
        desktop = CycleDesktop(profile, window, TextReader(), owner=owner, emit=emit)
        loop = TributeLoop(desktop, log=lambda message: emit("detail", detail=message))
        loop.wait("已登录的星图（游戏文字须为繁体中文或 English）", Frame.map_search, 25)
        return CycleRunner(LiveCycleGame(loop, emit), options, emit=emit,
                           finish_requested=lambda: desktop.finish_requested).run()


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("tribute-cycle", help="Run repeated AP refill and Tribute Vessel batches.")
    parser.add_argument("--captain", required=True, help="Exact in-game nickname without the alliance tag.")
    parser.add_argument("--level", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    stop_mode = parser.add_mutually_exclusive_group()
    stop_mode.add_argument("--hours", type=float, help="Finish after this many hours.")
    stop_mode.add_argument("--total-rallies", type=int, help="Start finishing after this many verified rallies.")
    parser.add_argument("--strict-count", action="store_true", help="With --total-rallies, never exceed the count, even during AP cleanup.")
    parser.add_argument("--result-timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--repair-after-rally", action=argparse.BooleanOptionalAction, default=True,
                        help="Click one recognized quick-repair control after each completed rally (default on).")
    parser.add_argument("--launch-path", type=Path, help="Optional game launcher executable if the game is closed.")
    parser.add_argument("--execute", action="store_true", help="Use in-game action points and the first potion row.")
    parser.add_argument("--event-log", type=Path, help="New JSONL event file; not overwritten.")
    parser.add_argument("--owner-pid", type=int, help=argparse.SUPPRESS)
    parser.set_defaults(func=command, tribute_cycle_parser=parser)


def command(args: argparse.Namespace) -> int:
    try:
        cfg = CycleOptions(args.captain, args.level, args.batch_size, args.hours, args.result_timeout,
                           args.launch_path, args.repair_after_rally, args.total_rallies, args.strict_count)
    except CycleError as exc:
        args.tribute_cycle_parser.error(exc.code)
    if not args.execute:
        plan = {"mode": "plan", "size": [1920, 1080], "action_point_cap": CAPACITY,
                "level": cfg.level, "batch_size": cfg.batch_size, "hours": cfg.hours,
                "repair_after_rally": cfg.repair_after_rally, "final_ap_below": None if cfg.strict_count else CAPACITY}
        if cfg.total_rallies is not None:
            plan.update(total_rallies=cfg.total_rallies, strict_count=cfg.strict_count)
        print(json.dumps(plan, ensure_ascii=False))
        return 0

    with (args.event_log.open("x", encoding="utf-8", buffering=1) if args.event_log else nullcontext()) as stream:
        def emit(event: str, **fields: object) -> None:
            record = {"event": event, "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
            print(json.dumps(record, ensure_ascii=False), file=stream, flush=True)

        emit("preparing")
        try:
            summary = _live(cfg, args.profile, emit, args.owner_pid)
        except KeyboardInterrupt:
            emit("stopped", code="interrupted", detail="Ctrl+C")
            return 2
        except Exception as exc:
            emit("stopped", code=exc.code if isinstance(exc, CycleError) else "runtime_stop", detail=str(exc))
            return 2
        if summary.ap >= summary.capacity:
            emit("stopped", code="count_limit_full_ap", **vars(summary))
            return 2
        emit("finished", **vars(summary))
    return 0
