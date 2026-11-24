from __future__ import annotations

import time
from typing import Any, Protocol
import ctypes

import win32api
import win32con

from .window import GameWindow


KEYS = {
    "escape": win32con.VK_ESCAPE,
    "esc": win32con.VK_ESCAPE,
    "enter": win32con.VK_RETURN,
    "return": win32con.VK_RETURN,
    "tab": win32con.VK_TAB,
    "space": win32con.VK_SPACE,
}

_USER32 = ctypes.windll.user32
_ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _InputUnion)]


INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101


class InputBackend(Protocol):
    name: str

    def move(self, screen_x: int, screen_y: int) -> None:
        ...

    def mouse_down(self) -> None:
        ...

    def mouse_up(self) -> None:
        ...

    def click(self, window: GameWindow, screen_x: int, screen_y: int, client_x: int, client_y: int, clicks: int, pause: float) -> None:
        ...

    def scroll(self, window: GameWindow, screen_x: int, screen_y: int, wheel_delta: int, pause: float) -> None:
        ...

    def drag(
        self,
        window: GameWindow,
        start_screen: tuple[int, int],
        end_screen: tuple[int, int],
        steps: int,
        pause: float,
    ) -> None:
        ...

    def press_key(self, window: GameWindow, key: str, pause: float) -> None:
        ...

    def type_text(self, window: GameWindow, text: str, pause: float) -> None:
        ...


def _virtual_screen() -> tuple[int, int, int, int]:
    left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    return left, top, width, height


def _absolute_mouse_coord(x: int, y: int) -> tuple[int, int]:
    left, top, width, height = _virtual_screen()
    absolute_x = round((x - left) * 65535 / max(1, width - 1))
    absolute_y = round((y - top) * 65535 / max(1, height - 1))
    return absolute_x, absolute_y


def _send_mouse(flags: int, x: int = 0, y: int = 0, data: int = 0) -> bool:
    extra = ctypes.c_ulong(0)
    mouse_input = _MouseInput(x, y, data, flags, 0, ctypes.pointer(extra))
    event = _Input(INPUT_MOUSE, _InputUnion(mi=mouse_input))
    sent = _USER32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    return sent == 1


def _click_with_send_input(screen_x: int, screen_y: int, pause: float) -> None:
    absolute_x, absolute_y = _absolute_mouse_coord(screen_x, screen_y)
    move_flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    if not _send_mouse(move_flags, absolute_x, absolute_y):
        raise OSError(f"SendInput move failed for ({screen_x}, {screen_y})")
    time.sleep(pause)
    if not _send_mouse(MOUSEEVENTF_LEFTDOWN):
        raise OSError("SendInput left down failed")
    time.sleep(pause)
    if not _send_mouse(MOUSEEVENTF_LEFTUP):
        raise OSError("SendInput left up failed")


def _move_with_send_input(screen_x: int, screen_y: int) -> None:
    absolute_x, absolute_y = _absolute_mouse_coord(screen_x, screen_y)
    move_flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    if not _send_mouse(move_flags, absolute_x, absolute_y):
        raise OSError(f"SendInput move failed for ({screen_x}, {screen_y})")


def probe_send_input_move(screen_x: int, screen_y: int, *, pause: float = 0.05, tolerance: int = 2) -> dict[str, Any]:
    before = win32api.GetCursorPos()
    target = (int(screen_x), int(screen_y))
    error = None
    try:
        _move_with_send_input(*target)
        time.sleep(pause)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    after = win32api.GetCursorPos()
    ok = abs(after[0] - target[0]) <= tolerance and abs(after[1] - target[1]) <= tolerance
    restore_error = None
    try:
        _move_with_send_input(int(before[0]), int(before[1]))
        time.sleep(pause)
    except Exception as exc:
        restore_error = {"type": type(exc).__name__, "message": str(exc)}
    restored = win32api.GetCursorPos()
    return {
        "target": list(target),
        "ok": ok,
        "before": list(before),
        "after": list(after),
        "restored": list(restored),
        "restore_ok": abs(restored[0] - before[0]) <= tolerance and abs(restored[1] - before[1]) <= tolerance,
        "error": error,
        "restore_error": restore_error,
    }


def _click_with_window_message(window: GameWindow, client_x: int, client_y: int, pause: float) -> None:
    lparam = (client_y << 16) | (client_x & 0xFFFF)
    if not _USER32.PostMessageW(window.hwnd, WM_LBUTTONDOWN, 1, lparam):
        raise OSError(f"PostMessage WM_LBUTTONDOWN failed for client ({client_x}, {client_y})")
    time.sleep(pause)
    if not _USER32.PostMessageW(window.hwnd, WM_LBUTTONUP, 0, lparam):
        raise OSError(f"PostMessage WM_LBUTTONUP failed for client ({client_x}, {client_y})")


class SendInputBackend:
    name = "send_input"

    def move(self, screen_x: int, screen_y: int) -> None:
        _move_with_send_input(screen_x, screen_y)

    def mouse_down(self) -> None:
        if not _send_mouse(MOUSEEVENTF_LEFTDOWN):
            raise OSError("SendInput left down failed")

    def mouse_up(self) -> None:
        if not _send_mouse(MOUSEEVENTF_LEFTUP):
            raise OSError("SendInput left up failed")

    def click(self, window: GameWindow, screen_x: int, screen_y: int, client_x: int, client_y: int, clicks: int, pause: float) -> None:
        window.activate()
        for _ in range(clicks):
            _click_with_send_input(screen_x, screen_y, pause)
            time.sleep(pause)

    def scroll(self, window: GameWindow, screen_x: int, screen_y: int, wheel_delta: int, pause: float) -> None:
        window.activate()
        self.move(screen_x, screen_y)
        time.sleep(pause)
        if not _send_mouse(MOUSEEVENTF_WHEEL, data=int(wheel_delta)):
            raise OSError(f"SendInput wheel failed for delta {wheel_delta}")

    def drag(
        self,
        window: GameWindow,
        start_screen: tuple[int, int],
        end_screen: tuple[int, int],
        steps: int,
        pause: float,
    ) -> None:
        window.activate()
        self.move(*start_screen)
        time.sleep(pause)
        self.mouse_down()
        for index in range(1, max(1, steps) + 1):
            t = index / max(1, steps)
            x = round(start_screen[0] + (end_screen[0] - start_screen[0]) * t)
            y = round(start_screen[1] + (end_screen[1] - start_screen[1]) * t)
            self.move(x, y)
            time.sleep(pause)
        self.mouse_up()

    def press_key(self, window: GameWindow, key: str, pause: float) -> None:
        normalized = key.casefold()
        if normalized not in KEYS:
            raise ValueError(f"Unsupported key: {key!r}")
        window.activate()
        vk = KEYS[normalized]
        win32api.keybd_event(vk, 0, 0, 0)
        time.sleep(pause)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)

    def type_text(self, window: GameWindow, text: str, pause: float) -> None:
        raise NotImplementedError("send_input text entry is not implemented yet")


class PostMessageBackend:
    name = "post_message"

    def move(self, screen_x: int, screen_y: int) -> None:
        raise NotImplementedError("post_message move is not supported")

    def mouse_down(self) -> None:
        raise NotImplementedError("post_message mouse_down requires window-relative coordinates")

    def mouse_up(self) -> None:
        raise NotImplementedError("post_message mouse_up requires window-relative coordinates")

    def click(self, window: GameWindow, screen_x: int, screen_y: int, client_x: int, client_y: int, clicks: int, pause: float) -> None:
        window.activate()
        for _ in range(clicks):
            _click_with_window_message(window, client_x, client_y, pause)
            time.sleep(pause)

    def scroll(self, window: GameWindow, screen_x: int, screen_y: int, wheel_delta: int, pause: float) -> None:
        raise NotImplementedError("post_message scroll is not supported")

    def drag(
        self,
        window: GameWindow,
        start_screen: tuple[int, int],
        end_screen: tuple[int, int],
        steps: int,
        pause: float,
    ) -> None:
        raise NotImplementedError("post_message drag is not supported")

    def press_key(self, window: GameWindow, key: str, pause: float) -> None:
        normalized = key.casefold()
        if normalized not in KEYS:
            raise ValueError(f"Unsupported key: {key!r}")
        vk = KEYS[normalized]
        scan_code = win32api.MapVirtualKey(vk, 0)
        lparam_down = 1 | (scan_code << 16)
        lparam_up = lparam_down | (1 << 30) | (1 << 31)
        if not _USER32.PostMessageW(window.hwnd, WM_KEYDOWN, vk, lparam_down):
            raise OSError(f"PostMessage WM_KEYDOWN failed for key {normalized!r}")
        time.sleep(pause)
        if not _USER32.PostMessageW(window.hwnd, WM_KEYUP, vk, lparam_up):
            raise OSError(f"PostMessage WM_KEYUP failed for key {normalized!r}")

    def type_text(self, window: GameWindow, text: str, pause: float) -> None:
        raise NotImplementedError("post_message text entry is not supported")


class PyAutoGuiBackend:
    name = "pyautogui"

    def _pyautogui(self) -> Any:
        try:
            import pyautogui
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError("pyautogui backend requires installing pyautogui") from exc
        pyautogui.FAILSAFE = False
        return pyautogui

    def move(self, screen_x: int, screen_y: int) -> None:
        self._pyautogui().moveTo(screen_x, screen_y)

    def mouse_down(self) -> None:
        self._pyautogui().mouseDown()

    def mouse_up(self) -> None:
        self._pyautogui().mouseUp()

    def click(self, window: GameWindow, screen_x: int, screen_y: int, client_x: int, client_y: int, clicks: int, pause: float) -> None:
        window.activate()
        self._pyautogui().click(x=screen_x, y=screen_y, clicks=clicks, interval=pause)

    def scroll(self, window: GameWindow, screen_x: int, screen_y: int, wheel_delta: int, pause: float) -> None:
        window.activate()
        pyautogui = self._pyautogui()
        pyautogui.moveTo(screen_x, screen_y)
        time.sleep(pause)
        pyautogui.scroll(int(wheel_delta))

    def drag(
        self,
        window: GameWindow,
        start_screen: tuple[int, int],
        end_screen: tuple[int, int],
        steps: int,
        pause: float,
    ) -> None:
        window.activate()
        pyautogui = self._pyautogui()
        pyautogui.moveTo(*start_screen)
        pyautogui.dragTo(*end_screen, duration=max(0.0, steps * pause), button="left")

    def press_key(self, window: GameWindow, key: str, pause: float) -> None:
        window.activate()
        pyautogui = self._pyautogui()
        pyautogui.keyDown(key)
        time.sleep(pause)
        pyautogui.keyUp(key)

    def type_text(self, window: GameWindow, text: str, pause: float) -> None:
        window.activate()
        self._pyautogui().write(text, interval=pause)


INPUT_BACKENDS: dict[str, InputBackend] = {
    "send_input": SendInputBackend(),
    "post_message": PostMessageBackend(),
    "pyautogui": PyAutoGuiBackend(),
}


def supported_input_backends() -> list[str]:
    return sorted(INPUT_BACKENDS)


def get_input_backend(name: str) -> InputBackend:
    try:
        return INPUT_BACKENDS[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported input backend: {name!r}") from exc


def click_normalized(
    window: GameWindow,
    x: float,
    y: float,
    *,
    label: str = "",
    clicks: int = 1,
    dry_run: bool = True,
    pause: float = 0.08,
    backend: str = "send_input",
) -> dict[str, Any]:
    screen_x, screen_y = window.normalized_to_screen(x, y)
    client_x, client_y = window.normalized_to_client(x, y)
    planned = {
        "type": "click",
        "label": label,
        "normalized": [round(x, 4), round(y, 4)],
        "client": [client_x, client_y],
        "screen": [screen_x, screen_y],
        "clicks": clicks,
        "backend": backend,
        "dry_run": dry_run,
    }
    if dry_run:
        return planned

    get_input_backend(backend).click(window, screen_x, screen_y, client_x, client_y, clicks, pause)
    return planned


def scroll_normalized(
    window: GameWindow,
    x: float,
    y: float,
    *,
    wheel_delta: int,
    label: str = "",
    dry_run: bool = True,
    pause: float = 0.05,
    backend: str = "send_input",
) -> dict[str, Any]:
    screen_x, screen_y = window.normalized_to_screen(x, y)
    client_x, client_y = window.normalized_to_client(x, y)
    planned = {
        "type": "scroll",
        "label": label,
        "normalized": [round(x, 4), round(y, 4)],
        "client": [client_x, client_y],
        "screen": [screen_x, screen_y],
        "wheel_delta": wheel_delta,
        "backend": backend,
        "dry_run": dry_run,
    }
    if dry_run:
        return planned

    get_input_backend(backend).scroll(window, screen_x, screen_y, int(wheel_delta), pause)
    return planned


def drag_normalized(
    window: GameWindow,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    *,
    label: str = "",
    dry_run: bool = True,
    steps: int = 12,
    pause: float = 0.02,
    backend: str = "send_input",
) -> dict[str, Any]:
    start_screen = window.normalized_to_screen(from_x, from_y)
    end_screen = window.normalized_to_screen(to_x, to_y)
    start_client = window.normalized_to_client(from_x, from_y)
    end_client = window.normalized_to_client(to_x, to_y)
    planned = {
        "type": "drag",
        "label": label,
        "from_normalized": [round(from_x, 4), round(from_y, 4)],
        "to_normalized": [round(to_x, 4), round(to_y, 4)],
        "from_client": list(start_client),
        "to_client": list(end_client),
        "from_screen": list(start_screen),
        "to_screen": list(end_screen),
        "steps": steps,
        "backend": backend,
        "dry_run": dry_run,
    }
    if dry_run:
        return planned

    get_input_backend(backend).drag(window, start_screen, end_screen, steps, pause)
    return planned


def press_key(
    window: GameWindow,
    key: str,
    *,
    dry_run: bool = True,
    pause: float = 0.05,
    backend: str = "send_input",
) -> dict[str, Any]:
    normalized = key.casefold()
    if normalized not in KEYS:
        raise ValueError(f"Unsupported key: {key!r}")
    planned = {"type": "press_key", "key": normalized, "backend": backend, "dry_run": dry_run}
    if dry_run:
        return planned

    get_input_backend(backend).press_key(window, normalized, pause)
    return planned
