from __future__ import annotations

import ctypes
from ctypes import wintypes
import re
import time
from dataclasses import dataclass

import win32api
import win32con
import win32gui
import win32process


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def as_bbox(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    title: str
    process_id: int
    window_rect: Rect
    client_rect: Rect

    def normalized_to_client(self, x: float, y: float) -> tuple[int, int]:
        return round(self.client_rect.width * x), round(self.client_rect.height * y)

    def normalized_to_screen(self, x: float, y: float) -> tuple[int, int]:
        client_x, client_y = self.normalized_to_client(x, y)
        return self.client_rect.left + client_x, self.client_rect.top + client_y

    def activate(self) -> bool:
        return activate_window(self.hwnd)


def _is_foreground(hwnd: int) -> bool:
    try:
        return int(ctypes.windll.user32.GetForegroundWindow()) == int(hwnd)
    except Exception:
        return False


def _try_set_foreground(hwnd: int) -> bool:
    try:
        if ctypes.windll.user32.SetForegroundWindow(hwnd):
            return True
    except Exception:
        return _is_foreground(hwnd)
    return _is_foreground(hwnd)


def _try_bring_to_top(hwnd: int) -> bool:
    try:
        user32 = ctypes.windll.user32
        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.05)
        if user32.SetForegroundWindow(hwnd):
            return True
    except Exception:
        return _is_foreground(hwnd)
    return _is_foreground(hwnd)


def _try_thread_input_foreground(hwnd: int) -> bool:
    attached = False
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        foreground_hwnd = int(user32.GetForegroundWindow())
        if not foreground_hwnd:
            return _is_foreground(hwnd)

        foreground_thread_id = int(user32.GetWindowThreadProcessId(foreground_hwnd, None))
        current_thread_id = int(kernel32.GetCurrentThreadId())
        if foreground_thread_id and user32.AttachThreadInput(current_thread_id, foreground_thread_id, True):
            attached = True

        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
    except Exception:
        pass
    finally:
        if attached:
            try:
                ctypes.windll.user32.AttachThreadInput(current_thread_id, foreground_thread_id, False)
            except Exception:
                pass
    return _is_foreground(hwnd)


def _try_switch_to_this_window(hwnd: int) -> bool:
    try:
        ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
        time.sleep(0.05)
    except Exception:
        return _is_foreground(hwnd)
    return _is_foreground(hwnd)


def activate_window(hwnd: int) -> bool:
    """Bring a Windows game window to the foreground with several safe retries."""
    try:
        user32 = ctypes.windll.user32
        if not hwnd or not user32.IsWindow(hwnd):
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.1)
    except Exception:
        return False

    return (
        _try_set_foreground(hwnd)
        or _try_bring_to_top(hwnd)
        or _try_thread_input_foreground(hwnd)
        or _try_switch_to_this_window(hwnd)
    )


def describe_window_state(window: GameWindow) -> dict[str, object]:
    foreground_hwnd = int(win32gui.GetForegroundWindow())
    minimized = bool(win32gui.IsIconic(window.hwnd))
    dpi = None
    try:
        dpi = int(ctypes.windll.user32.GetDpiForWindow(window.hwnd))
    except Exception:
        pass
    return {
        "foreground": foreground_hwnd == window.hwnd,
        "foreground_hwnd": foreground_hwnd,
        "minimized": minimized,
        "dpi": dpi,
        "client_size": [window.client_rect.width, window.client_rect.height],
        "process_id": window.process_id,
    }


def resize_client_area(
    window: GameWindow,
    width: int,
    height: int,
    *,
    center: bool = True,
    tolerance: int = 2,
    wait_seconds: float = 1.0,
) -> dict[str, object]:
    """Resize the native window so the game client area matches the requested size."""
    ensure_dpi_awareness()
    if width <= 0 or height <= 0:
        raise ValueError("Client width and height must be positive.")

    hwnd = window.hwnd
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.1)
        window = _window_info(hwnd)

    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    dpi = 96
    try:
        dpi = int(ctypes.windll.user32.GetDpiForWindow(hwnd))
    except Exception:
        pass

    rect = wintypes.RECT(0, 0, int(width), int(height))
    try:
        adjust_ok = bool(ctypes.windll.user32.AdjustWindowRectExForDpi(ctypes.byref(rect), style, False, exstyle, dpi))
    except Exception:
        adjust_ok = bool(ctypes.windll.user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, exstyle))

    adjusted_outer_width = int(rect.right - rect.left)
    adjusted_outer_height = int(rect.bottom - rect.top)
    measured_extra_width = max(0, window.window_rect.width - window.client_rect.width)
    measured_extra_height = max(0, window.window_rect.height - window.client_rect.height)
    outer_width = int(width + measured_extra_width)
    outer_height = int(height + measured_extra_height)
    left = window.window_rect.left
    top = window.window_rect.top
    monitor_work = None
    if center:
        monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        info = win32api.GetMonitorInfo(monitor)
        work_left, work_top, work_right, work_bottom = info["Work"]
        monitor_work = [work_left, work_top, work_right, work_bottom]
        work_width = work_right - work_left
        work_height = work_bottom - work_top
        left = work_left + max(0, (work_width - outer_width) // 2)
        top = work_top + max(0, (work_height - outer_height) // 2)

    set_error = None
    set_ok = False
    try:
        set_ok = bool(
            win32gui.SetWindowPos(
                hwnd,
                None,
                int(left),
                int(top),
                outer_width,
                outer_height,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
            )
        )
    except Exception as exc:
        set_error = {"type": exc.__class__.__name__, "message": str(exc)}

    if wait_seconds > 0:
        time.sleep(wait_seconds)

    after = _window_info(hwnd)
    actual_width = after.client_rect.width
    actual_height = after.client_rect.height
    width_ok = abs(actual_width - width) <= tolerance
    height_ok = abs(actual_height - height) <= tolerance
    applied = bool(width_ok and height_ok)

    return {
        "status": "ok" if applied else "error",
        "requested_client_size": [int(width), int(height)],
        "actual_client_size": [actual_width, actual_height],
        "tolerance": int(tolerance),
        "applied": applied,
        "adjust_ok": adjust_ok,
        "set_window_pos_ok": set_ok,
        "set_window_pos_error": set_error,
        "dpi": dpi,
        "requested_outer_size": [outer_width, outer_height],
        "adjusted_outer_size": [adjusted_outer_width, adjusted_outer_height],
        "measured_client_inset": [measured_extra_width, measured_extra_height],
        "requested_window_pos": [int(left), int(top)],
        "monitor_work": monitor_work,
        "before": _window_to_record(window),
        "after": _window_to_record(after),
    }


def ensure_dpi_awareness() -> None:
    """Match screenshot and click coordinates on high-DPI Windows."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _rect_from_tuple(rect: tuple[int, int, int, int]) -> Rect:
    return Rect(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))


def _window_info(hwnd: int) -> GameWindow:
    title = win32gui.GetWindowText(hwnd)
    _, process_id = win32process.GetWindowThreadProcessId(hwnd)
    window_rect = _rect_from_tuple(win32gui.GetWindowRect(hwnd))
    client_left_top = win32gui.ClientToScreen(hwnd, (0, 0))
    client_right_bottom_raw = win32gui.GetClientRect(hwnd)[2:4]
    client_right_bottom = win32gui.ClientToScreen(hwnd, client_right_bottom_raw)
    client_rect = Rect(
        client_left_top[0],
        client_left_top[1],
        client_right_bottom[0],
        client_right_bottom[1],
    )
    return GameWindow(
        hwnd=hwnd,
        title=title,
        process_id=process_id,
        window_rect=window_rect,
        client_rect=client_rect,
    )


def _window_to_record(window: GameWindow) -> dict[str, object]:
    return {
        "hwnd": window.hwnd,
        "title": window.title,
        "process_id": window.process_id,
        "window_rect": window.window_rect.__dict__,
        "client_rect": window.client_rect.__dict__,
        "client_size": [window.client_rect.width, window.client_rect.height],
    }


def find_by_class_and_title(class_name: str, title: str) -> GameWindow | None:
    """Match March7thAssistant's primary Unity-window lookup strategy."""
    ensure_dpi_awareness()
    hwnd = win32gui.FindWindow(class_name, title)
    if not hwnd:
        return None
    if not win32gui.IsWindowVisible(hwnd):
        return None
    return _window_info(hwnd)


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _title_matches(current_title: str, wanted_title: str) -> bool:
    current = current_title.casefold()
    wanted = wanted_title.casefold()
    if wanted in current:
        return True
    normalized_current = _normalize_title(current_title)
    normalized_wanted = _normalize_title(wanted_title)
    return bool(normalized_wanted and normalized_wanted in normalized_current)


def list_matching_windows(title: str) -> list[GameWindow]:
    ensure_dpi_awareness()
    matches: list[GameWindow] = []

    def callback(hwnd: int, _extra: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        current_title = win32gui.GetWindowText(hwnd)
        if _title_matches(current_title, title):
            matches.append(_window_info(hwnd))
        return True

    win32gui.EnumWindows(callback, None)
    return matches


def find_game_window(
    title: str = "Foundation: Galactic Frontier",
    class_name: str = "UnityWndClass",
) -> GameWindow:
    class_match = find_by_class_and_title(class_name, title)
    if class_match is not None:
        return class_match

    matches = list_matching_windows(title)
    if not matches:
        raise RuntimeError(
            f"No visible game window matched class/title {class_name!r}/{title!r} "
            "or title substring fallback."
        )
    if len(matches) > 1:
        titles = ", ".join(f"{item.hwnd}:{item.title}" for item in matches)
        raise RuntimeError(f"Multiple matching game windows found: {titles}")
    return matches[0]
