"""Guarded map -> Tribute rally -> fresh battle report loop and AP refill."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import math
import time
from typing import Callable, Protocol, TypeVar

import win32api
import win32con
import win32event
import win32gui

from foundation_assistant.games import GameProfile, get_profile
from foundation_assistant.tribute_loop_vision import Frame, Point, RALLY_COST, SIZE, TextReader
from foundation_assistant.vision.screenshot import capture_window
from foundation_assistant.win.input import get_input_backend
from foundation_assistant.win.window import GameWindow, find_game_window, resize_client_area


MIN_WAIT = 180
AP_COST = RALLY_COST
MAIL_FIRST_POLL = 45  # Fallback only; the quick-repair signal is watched immediately.
MAIL_POLL_INTERVAL = 20
T = TypeVar("T")


class Stop(RuntimeError):
    """Unverified state: stop with no further inputs."""


class RetryBeforeInput(RuntimeError):
    """The target must be re-read; no mouse-down was sent for this attempt."""


class RallySetupNotOpened(Stop):
    """The red navigation button returned to the map; no final input was attempted."""


class LoopIO(Protocol):
    def frame(self) -> Frame: ...
    def pause(self, seconds: float) -> None: ...
    def click(self, point: Point) -> None: ...
    def drag(self, start: Point, end: Point) -> None: ...


def prepare_window(profile: GameProfile) -> GameWindow:
    window = find_game_window(profile.window_title, profile.window_class)
    if win32gui.GetWindowPlacement(window.hwnd)[1] == win32con.SW_SHOWMAXIMIZED:
        win32gui.ShowWindow(window.hwnd, win32con.SW_RESTORE)
        window = find_game_window(profile.window_title, profile.window_class)
    if win32gui.IsIconic(window.hwnd) or (window.client_rect.width, window.client_rect.height) != SIZE:
        result = resize_client_area(window, *SIZE, tolerance=0)
        if not result["applied"]:
            size = "×".join(map(str, result["actual_client_size"]))
            error = result.get("set_window_pos_error") or {}
            raise Stop(f"无法调到 1920×1080，当前 {size}。{error.get('message', '')} "
                       "若游戏以管理员身份运行，请从管理员 PowerShell 启动脚本；仍失败请在游戏内改成 1080p 窗口模式。")
        window = find_game_window(profile.window_title, profile.window_class)
    if (window.client_rect.width, window.client_rect.height) != SIZE:
        raise Stop("游戏未保持 1920×1080，已停止。")
    monitor = win32api.MonitorFromWindow(window.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    ml, mt, mr, mb = win32api.GetMonitorInfo(monitor)["Monitor"]
    left, top, right, bottom = window.client_rect.as_bbox()
    if not (ml <= left < right <= mr and mt <= top < bottom <= mb):
        raise Stop("1080p 画面没完整放在同一块屏幕内；请移动游戏窗口或改用 1080p 无边框模式。")
    return window


@contextmanager
def single_instance():
    handle = win32event.CreateMutex(None, False, r"Local\FoundationAssistantTributeLoop")
    try:
        state = win32event.WaitForSingleObject(handle, 0)
        if state not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
            raise Stop("已有一个贡品船脚本正在运行。")
        try:
            yield
        finally:
            win32event.ReleaseMutex(handle)
    finally:
        handle.Close()


class Desktop:
    def __init__(self, profile: GameProfile, window: GameWindow, reader: TextReader) -> None:
        self.profile = profile
        self.window = window
        self.reader = reader
        self.input = get_input_backend("send_input")
        self._start_window()

    def _start_window(self) -> None:
        if not self.window.activate():
            raise Stop("没法将游戏切到前台。请手动把游戏切到前台后重试。")
        self.check()

    def check(self) -> None:
        if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
            raise Stop("收到 F8 停止。")
        hwnd = self.window.hwnd
        if win32gui.GetForegroundWindow() != hwnd or win32gui.IsIconic(hwnd):
            raise Stop("游戏不再是前台窗口，已停止。")
        current = find_game_window(self.profile.window_title, self.profile.window_class)
        if (current.hwnd, current.process_id, current.client_rect) != (
            hwnd, self.window.process_id, self.window.client_rect
        ):
            raise Stop("游戏窗口位置、尺寸或进程已变化，已停止。")

    def frame(self) -> Frame:
        self.check()
        image = capture_window(self.window)
        self.check()
        return Frame(image, self.profile.templates_dir, self.reader)

    def pause(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            self.check()
            time.sleep(min(0.15, remaining))

    def _screen_point(self, point: Point) -> Point:
        if not (0 <= point[0] < SIZE[0] and 0 <= point[1] < SIZE[1]):
            raise Stop("控制点超出游戏画面。")
        location = self.window.client_rect.left + point[0], self.window.client_rect.top + point[1]
        hwnd = self.window.hwnd
        target = win32gui.WindowFromPoint(location)
        if target != hwnd and not win32gui.IsChild(hwnd, target):
            raise Stop("游戏控制点被其他窗口遮挡。")
        return location

    def _mouse_start(self, point: Point) -> None:
        self.check()
        location = self._screen_point(point)
        self.input.move(*location)
        self.pause(0.04)
        if math.dist(win32api.GetCursorPos(), self._screen_point(point)) > 3:
            raise Stop("鼠标没到达预期位置，可能被手动移动或当前权限不足。")
        self.check()
        self.input.mouse_down()

    def click(self, point: Point) -> None:
        self._mouse_start(point)
        try:
            self.pause(0.06)
        finally:
            self.input.mouse_up()

    def drag(self, start: Point, end: Point) -> None:
        self.check()
        self._screen_point(end)
        self._mouse_start(start)
        try:
            for i in range(1, 17):
                self.check()
                point = (round(start[0] + (end[0] - start[0]) * i / 16),
                         round(start[1] + (end[1] - start[1]) * i / 16))
                self.input.move(*self._screen_point(point))
                self.pause(0.022)
        finally:
            self.input.mouse_up()


class TributeLoop:
    def __init__(self, io: LoopIO, *, clock=time.monotonic, log=print) -> None:
        self.io = io
        self.clock = clock
        self.log = log

    def wait(self, label: str, check: Callable[[Frame], T | None], timeout: float = 10) -> T:
        deadline = self.clock() + timeout
        while True:
            found = check(self.io.frame())
            if found is not None:
                return found
            if self.clock() >= deadline:
                raise Stop(f"没有确认到「{label}」，已停止，不盲点或重试提交。")
            self.io.pause(min(0.35, max(0, deadline - self.clock())))

    def step(self, label: str, check: Callable[[Frame], Point | None], *, timeout: float = 10,
             before_click: Callable[[], bool] | None = None, stabilize: bool = False) -> bool:
        for attempt in range(3):
            if stabilize:
                # Search can pan the map before the target card settles.
                # Wait for two consecutive matching positions before any input.
                previous = None

                def stable(frame: Frame) -> Point | None:
                    nonlocal previous
                    point = check(frame)
                    matches = point is not None and previous is not None and math.dist(point, previous) <= 10
                    previous = point
                    return point if matches else None

                latest = self.wait(label, stable, timeout)
            else:
                point = self.wait(label, check, timeout)
                latest = check(self.io.frame())
                if latest is None or math.dist(point, latest) > 10:
                    raise Stop(f"「{label}」画面不稳定，已停止。")
            if before_click is not None and not before_click():
                return False
            try:
                self.io.click(latest)
            except RetryBeforeInput:
                if attempt == 2:
                    raise Stop(f"「{label}」点击前连续受到输入或焦点干扰，未点击。") from None
                self.log(f"「{label}」还未点击，重新截图确认。")
                self.io.pause(0.55)
            else:
                return True
        raise AssertionError("unreachable")

    def set_level(self, desired: int) -> None:
        previous = None
        up_increases = True
        changed = False
        distance = 67
        unchanged = 0
        input_retries = 0
        for _ in range(60):
            current, (x, y) = self.wait("贡品船等级数字", Frame.level_picker)
            if current == desired:
                self.log(f"已读回等级：{current}")
                return
            if previous is not None:
                if current == previous:
                    unchanged += 1
                    if unchanged >= 3:
                        raise Stop(f"等级停在 {current}，无法调到 {desired}；可能超过当前可选范围。")
                    distance = min(85, distance + 9)
                else:
                    if not changed and (current - previous) * (desired - previous) < 0:
                        up_increases = not up_increases
                    changed = True
                    unchanged = 0
                    if (current - desired) * (previous - desired) < 0:
                        distance = max(45, distance - 10)
            up = (desired > current) == up_increases
            try:
                self.io.drag((x, y), (x, y + (-distance if up else distance)))
            except RetryBeforeInput:
                input_retries += 1
                if input_retries >= 3:
                    raise Stop("等级拖动前连续受到输入或焦点干扰，未开始拖动。") from None
                self.log("还未拖动，重新读取游戏等级。")
                previous, unchanged = None, 0
                self.io.pause(0.55)
                continue
            input_retries = 0
            previous = current
            self.io.pause(0.65)
        raise Stop(f"未能稳定调到 {desired} 级，已停止。")

    def start(self, level: int, *, preview: bool) -> float | None:
        if self.io.frame().search_header() is None:
            self.step("地图放大镜", Frame.map_search)
        self.wait("搜寻与贡品船选项", Frame.search_tab)
        if self.io.frame().search_tab(selected=True) is None:
            self.step("贡品船选项", Frame.search_tab)
        self.set_level(level)
        self.step("已核对等级的黄色搜寻按钮", lambda frame: frame.search_button(level))
        target = lambda frame: frame.target_rally(level) if frame.search_header() is None else None
        if preview:
            self.wait(f"{level} 级贡品船与红色集结", target, 24)
            self.log("预览已到目标卡片，没点红色/黄色集结，也没消耗体力。")
            return None
        self.step(f"{level} 级贡品船的红色集结（30 体力）", target, timeout=24, stabilize=True)
        self.wait_for_rally_setup()
        self.step("舰队评分页的黄色集结（30 体力）", Frame.setup_rally)
        return self.clock()

    def wait_for_rally_setup(self, timeout: float = 10) -> None:
        # A target can move or disappear between choosing it and the setup
        # transition. Only the clearly visible star map is a recoverable state.
        deadline = self.clock() + timeout
        while True:
            frame = self.io.frame()
            if frame.setup_rally() is not None:
                return
            if self.clock() >= deadline:
                if frame.repair_view() is not None:
                    raise RallySetupNotOpened("点了红色集结后仍在星图，没点黄色确认。")
                raise Stop("未确认舰队评分页，当前画面不明，没点黄色确认。")
            self.io.pause(min(0.35, max(0, deadline - self.clock())))

    def result(self, captain: str, level: int, sent: float, timeout: int) -> None:
        self.log("已点击黄色集结；至少等 180 秒，再核对本轮胜利战报。")
        deadline = sent + timeout
        self.io.pause(max(0, sent + MIN_WAIT - self.clock()))
        while self.clock() < deadline:
            if self.check_victory_mail(captain, level, sent, deadline):
                self.log(f"已确认本轮 {level} 级贡品船胜利。")
                return
            self.io.pause(min(15, max(0, deadline - self.clock())))
        raise Stop("超时，未确认本轮新战报；不会开始下一轮。请在游戏里检查是否仍在战斗或集结已取消。")

    def check_victory_mail(self, captain: str, level: int, sent: float, deadline: float) -> bool:
        self.step("地图邮件入口", lambda frame: frame.map_mail() if frame.map_search() else None)
        self.io.pause(0.65)
        _, _, selected = self.wait("邮件的巡猎列表", Frame.mail, 18)
        if not selected:
            self.step("巡猎邮件标签", lambda frame: page[1] if (page := frame.mail()) else None, timeout=18)
        captured_at = self.clock()
        report_frame = self.wait("选中的巡猎邮件标签", lambda frame: frame if ((page := frame.mail()) and page[2]) else None, 18)
        won = captured_at < deadline and report_frame.fresh_victory(captain, level, captured_at - sent)
        self.step("邮件返回箭头", Frame.mail_back)
        self.wait("返回星图", Frame.map_search)
        return won

    def wait_battle_end(self, captain: str, level: int, sent: float, timeout: int, *,
                        repair_already_visible: bool) -> str:
        """Watch the verified fleet sidebar immediately, and use new mail as a fallback."""
        deadline = sent + timeout
        mail_at = sent + MAIL_FIRST_POLL
        previous = None
        saw_clear_after_submit = False
        while self.clock() < deadline:
            view = self.io.frame().repair_view()
            if view is not None and view.button is None:
                saw_clear_after_submit = True
            point = view.button if view is not None and saw_clear_after_submit and not repair_already_visible else None
            if point is not None and previous is not None and math.dist(point, previous) <= 8:
                self.log("发现本轮新出现的快速维修按钮，判定战斗结束；不把按钮当胜利战报。")
                return "repair_icon"
            previous = point
            if view is not None and point is None and mail_at <= self.clock() < deadline:
                if self.check_victory_mail(captain, level, sent, deadline):
                    self.log(f"已确认本轮 {level} 级贡品船胜利战报。")
                    return "victory_mail"
                mail_at = self.clock() + MAIL_POLL_INTERVAL
            self.io.pause(min(0.8, max(0, deadline - self.clock())))
        raise Stop("结算超时：没有本轮新维修提示，也没有可确认的新胜利战报。不会发下一轮。")

    def repair_fleet(self) -> bool:
        """Click the normal gold quick-repair control at most once and verify it clears."""
        def button(frame: Frame) -> Point | None:
            view = frame.repair_view()
            return view.button if view is not None else None

        deadline = self.clock() + 3
        while True:
            view = self.io.frame().repair_view()
            if view is not None and view.button is not None:
                self.step("舰队栏金色快捷维修", button, timeout=3)
                break
            if self.clock() >= deadline:
                if view is not None:
                    return False
                raise Stop("未核对到可操作星图，没点击维修。")
            self.io.pause(min(0.35, max(0, deadline - self.clock())))

        def cleared(frame: Frame) -> Frame | None:
            view = frame.repair_view()
            return frame if view is not None and view.button is None else None

        self.io.pause(0.3)
        self.wait("快捷维修后，星图上的扳手提示消失", cleared, 8)
        self.io.pause(0.4)
        frame = self.wait("维修提示保持清除", cleared, 3)
        if frame.quick_repair_toast():
            self.log("已读到快捷维修消耗维修模组的提示。")
        else:
            self.log("已核对星图上的快捷维修按钮消失。")
        return True

    def open_profile(self) -> None:
        if self.io.frame().profile() is None:
            self.step("地图左上角头像", lambda frame: frame.map_avatar() if frame.map_search() else None)

    def identify_captain(self) -> str:
        self.open_profile()
        captain = self.wait("个人资料的游戏昵称（也可手动传 --captain）", Frame.profile_captain)
        self.step("个人资料关闭", Frame.profile_close)
        self.wait("返回星图", Frame.map_search)
        self.log("已从个人资料识别本账号昵称，用于核对战报。")
        return captain

    def read_action_points(self) -> tuple[int, int]:
        self.open_profile()
        points = self.wait("个人资料内的行动点", lambda frame: field[1] if (field := frame.profile()) else None)
        self.step("个人资料关闭", Frame.profile_close)
        self.wait("返回星图", Frame.map_search)
        return points

    def refill(self, *, preview: bool, only_if_below: int | None = None,
               allow_use: Callable[[], bool] | None = None) -> bool:
        """Return true only when the bulk control was used and the fill verified."""
        self.open_profile()
        profile = self.wait("个人资料行动点和加号", lambda frame: field if ((field := frame.profile()) and field[1]) else None)
        _, (current, total) = profile
        self.log(f"行动点：{current}/{total}")
        needed = min(total, only_if_below) if only_if_below is not None else total
        if current >= needed or (allow_use is not None and not allow_use()):
            self.step("个人资料关闭", Frame.profile_close)
            self.wait("返回星图", Frame.map_search)
            return False
        self.step("行动点旁边的加号", lambda frame: field[0] if ((field := frame.profile()) and field[1]) else None)
        points, _, bulk = self.wait("获得更多面板的行动点", lambda frame: pane if ((pane := frame.refill()) and pane[0]) else None)
        if points[1] != total:
            raise Stop("个人资料和补体力页面的上限不一致，没用药水。")
        applied = False
        if points[0] < needed and (allow_use is None or allow_use()):
            if bulk is None:
                raise Stop("未识别到第一行「使用」左侧的 ×数量，没用药水。")
            if preview:
                self.log("已识别第一行「使用」左边的 ×数量按钮，预览没有点击。")
                return False
            applied = self.step("第一行左边的 ×数量", lambda frame: self._refill_candidate(frame, total, needed),
                                before_click=allow_use)
        if applied:
            self.log("已点一次第一行的 ×数量；核对是否加满，不重复用药。")

            def filled(frame: Frame) -> tuple[int, int] | None:
                pane = frame.refill()
                profile_ap = None if pane else frame.profile()
                reading = pane[0] if pane else profile_ap[1] if profile_ap else None
                return reading if reading and reading[1] == total and reading[0] >= total else None

            new_current, _ = self.wait("体力已加满", filled, 12)
            self.log(f"已核对行动点：{new_current}/{total}。")
        if self.io.frame().refill():
            self.step("获得更多关闭", lambda frame: pane[1] if (pane := frame.refill()) else None)
        self.step("个人资料关闭", Frame.profile_close)
        self.wait("返回星图", Frame.map_search)
        return applied

    @staticmethod
    def _refill_candidate(frame: Frame, total: int, needed: int) -> Point | None:
        pane = frame.refill()
        if pane and pane[0] and pane[0][1] == total and pane[0][0] < needed:
            return pane[2]
        return None

    def run(self, *, captain: str, level: int, rounds: int, result_timeout: int, auto_refill: bool) -> None:
        captain = captain or self.identify_captain()
        round_number = 0
        while not rounds or round_number < rounds:
            round_number += 1
            self.log(f"第 {round_number} 轮：{level} 级贡品船")
            if auto_refill:
                self.refill(preview=False, only_if_below=AP_COST)
            sent = self.start(level, preview=False)
            if sent is None:
                raise Stop("集结未提交。")
            self.result(captain, level, sent, result_timeout)


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("tribute-loop", help="1080p 贡品船循环／补满体力（繁体中文或英文游戏）。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="调窗口并试走流程，但不点红色集结或使用药水。")
    mode.add_argument("--execute", action="store_true", help="实际执行，允许游戏内消耗体力／指定药水。")
    mode.add_argument("--resize-only", action="store_true", help="只调整并核对游戏画面到 1920×1080。")
    refill = parser.add_mutually_exclusive_group()
    refill.add_argument("--refill-only", action="store_true", help="只补体力，不发起集结。")
    refill.add_argument("--auto-refill", action="store_true", help="循环中不足 30 体力才补满。")
    parser.add_argument("--level", type=int, choices=range(1, 100), metavar="1..99", default=3, help="贡品船等级，默认 3。")
    parser.add_argument("--rounds", type=int, default=0, help="轮数；默认 0 表示持续到 F8 或遇到异常。")
    parser.add_argument("--captain", type=str.strip, default="", help="本账号的游戏昵称（不带公会前缀）；默认从个人资料读取。")
    parser.add_argument("--result-timeout", type=int, default=480, help="从提交起最多等待多少秒，默认 480，最少 181。")
    parser.set_defaults(func=command, tribute_loop_parser=parser)


def command(args: argparse.Namespace) -> int:
    if args.rounds < 0 or args.result_timeout <= MIN_WAIT:
        args.tribute_loop_parser.error("--rounds 必须 ≥0；--result-timeout 必须 >180。")
    if args.preview and args.auto_refill:
        args.tribute_loop_parser.error("请用 --preview --refill-only 单独预览补体力；--auto-refill 用于正式循环。")
    if args.resize_only and (args.refill_only or args.auto_refill):
        args.tribute_loop_parser.error("--resize-only 只改窗口，不与补体力选项同用。")
    if not (args.preview or args.execute or args.resize_only):
        if args.refill_only:
            print("仅计划：调 1080p → 头像 → 行动点加号 → 首行 ×数量 → 核对加满；没有操作游戏。")
        else:
            print(f"仅计划：调 1080p → 放大镜 → 贡品船 {args.level} 级 → 搜寻 → 两次集结 → "
                  "至少等 180 秒并核对本轮战报 → 下一轮；没有操作游戏。")
        return 0
    try:
        profile = get_profile(args.profile)
        reader = None if args.resize_only else TextReader()
        with single_instance():
            window = prepare_window(profile)
            print("已核对游戏画面为 1920×1080。", flush=True)
            if args.resize_only:
                return 0
            assert reader is not None
            loop = TributeLoop(Desktop(profile, window, reader), log=lambda message: print(message, flush=True))
            if args.refill_only:
                loop.refill(preview=args.preview)
            elif args.preview:
                loop.start(args.level, preview=True)
            else:
                loop.run(captain=args.captain, level=args.level, rounds=args.rounds,
                         result_timeout=args.result_timeout, auto_refill=args.auto_refill)
        return 0
    except ImportError as exc:
        print(f"无法加载体力／等级／战报所需的 OCR：{exc}。请安装 rapidocr 和 onnxruntime。", flush=True)
    except (RuntimeError, OSError, ValueError, win32gui.error) as exc:
        print(f"已停止：{exc}", flush=True)
    except KeyboardInterrupt:
        print("已停止（Ctrl+C）。", flush=True)
    return 2
