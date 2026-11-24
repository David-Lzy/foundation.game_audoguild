from __future__ import annotations

from types import SimpleNamespace

import pytest

from foundation_assistant import tribute_cycle as mod, tribute_loop as loop_mod
from foundation_assistant.games import get_profile
from foundation_assistant.tribute_loop import RetryBeforeInput, Stop, TributeLoop
from foundation_assistant.win.window import GameWindow, Rect


class TestHost:
    __test__ = False

    def __init__(self, monkeypatch):
        self.now = 0.0
        self.fg = 103
        self.iconic = False
        self.success_at = 1
        self.attempts = []
        self.events = []
        self.inputs = []
        self.keys = set()
        self.last_input = 0
        self.cursor = (55, 56)
        self.on_press = lambda: None
        self.on_sleep = lambda: None
        self.window = GameWindow(103, "Game", 506, Rect(200, 300, 2120, 1380), Rect(200, 300, 2120, 1380))
        self.current = self.window
        clock = SimpleNamespace(monotonic=lambda: self.now, sleep=self.sleep)
        monkeypatch.setattr(mod, "time", clock)
        monkeypatch.setattr(loop_mod, "time", clock)
        monkeypatch.setattr(mod, "find_game_window", lambda *_: self.current)
        monkeypatch.setattr(mod, "Frame", lambda image, *_: image)
        monkeypatch.setattr(mod, "capture_window", lambda _: "game pixels")
        monkeypatch.setattr(mod.win32api, "GetAsyncKeyState", lambda key: 0x8000 if key in self.keys else 0)
        monkeypatch.setattr(mod.win32api, "GetLastInputInfo", lambda: self.last_input)
        monkeypatch.setattr(mod.win32api, "GetTickCount", lambda: 1000 + int(self.now * 1000))
        monkeypatch.setattr(mod.win32api, "GetCursorPos", lambda: self.cursor)
        monkeypatch.setattr(mod.win32gui, "GetForegroundWindow", lambda: self.fg)
        monkeypatch.setattr(mod.win32gui, "IsIconic", lambda _: self.iconic)
        monkeypatch.setattr(mod.win32gui, "WindowFromPoint", lambda _: self.fg)
        monkeypatch.setattr(mod.win32gui, "IsChild", lambda *_: False)
        monkeypatch.setattr(GameWindow, "activate", lambda _: self.activate())
        monkeypatch.setattr(loop_mod, "get_input_backend", lambda _: self)

    def activate(self):
        self.attempts.append(self.now)
        if len(self.attempts) >= self.success_at:
            self.fg = self.window.hwnd
            self.iconic = False
            return True
        return False

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def desktop(self):
        return mod.CycleDesktop(get_profile(), self.window, None, emit=self.emit)

    def sleep(self, seconds):
        self.now += seconds
        self.on_sleep()

    def move(self, x, y):
        self.cursor = x, y
        self.inputs.append(("move", self.cursor))

    def mouse_down(self):
        self.inputs.append(("down", self.cursor))
        self.on_press()

    def mouse_up(self):
        self.inputs.append(("up", self.cursor))


def test_foreground_is_retried_on_each_loss_without_ending_the_wait(monkeypatch):
    host = TestHost(monkeypatch)
    desktop = host.desktop()
    for count in (3, 5):
        host.fg = 88
        host.success_at = count
        desktop.pause(0.4)
        assert host.fg == host.window.hwnd and len(host.attempts) == count
    assert [fields["attempts"] for key, fields in host.events if key == "focus_restored"] == [3, 2]
    assert not host.inputs


def test_recent_input_defers_activation_and_f9_is_seen_during_recovery(monkeypatch):
    host = TestHost(monkeypatch)
    desktop = host.desktop()
    host.fg = 88
    host.last_input = 1000
    host.keys = {mod.win32con.VK_F9, mod.win32con.VK_LBUTTON}
    host.on_sleep = lambda: host.keys.discard(mod.win32con.VK_LBUTTON) if host.now >= 0.7 else None
    desktop.check()
    assert desktop.finish_requested and host.attempts[0] >= 0.7
    assert [key for key, _ in host.events].count("finish_requested") == 1


def test_f8_stops_even_when_the_game_is_in_the_background(monkeypatch):
    host = TestHost(monkeypatch)
    desktop = host.desktop()
    host.fg = 88
    host.keys.add(mod.win32con.VK_F8)
    with pytest.raises(Stop, match="F8"):
        desktop.check()
    assert not host.attempts and not host.inputs


def test_cannot_restore_forever_when_windows_keeps_refusing(monkeypatch):
    host = TestHost(monkeypatch)
    desktop = host.desktop()
    host.fg = 88
    host.success_at = 100
    monkeypatch.setattr(mod, "FOCUS_TIMEOUT", 1.4)
    with pytest.raises(mod.CycleError) as error:
        desktop.check()
    assert error.value.code == "focus_recovery_failed" and len(host.attempts) >= 2 and not host.inputs


def test_discards_pixels_if_focus_switches_during_capture(monkeypatch):
    host = TestHost(monkeypatch)
    desktop = host.desktop()
    sequence = iter(["other app pixels", "new game pixels"])
    def capture(_):
        value = next(sequence)
        if value == "other app pixels":
            host.fg = 88
        return value
    monkeypatch.setattr(mod, "capture_window", capture)
    assert desktop.frame() == "new game pixels"
    assert len(host.attempts) == 1 and not host.inputs


def test_input_change_after_capture_rejects_the_point_before_moving(monkeypatch):
    host = TestHost(monkeypatch)
    desktop = host.desktop()
    desktop.frame()
    host.cursor = (56, 56)
    with pytest.raises(RetryBeforeInput):
        desktop.click((140, 325))
    assert not host.inputs


def test_mid_gesture_focus_loss_releases_and_never_replays_or_refocuses(monkeypatch):
    host = TestHost(monkeypatch)
    desktop = host.desktop()
    desktop.frame()
    host.on_press = lambda: setattr(host, "fg", 88)
    with pytest.raises(mod.CycleError) as error:
        desktop.click((140, 325))
    assert error.value.code == "input_interrupted"
    assert [name for name, _ in host.inputs] == ["move", "down", "up"]
    assert not host.attempts


def test_step_retry_uses_fresh_coordinates_and_does_not_duplicate_a_click(monkeypatch):
    host = TestHost(monkeypatch)
    desktop = host.desktop()
    seq = iter([(140, 325), (140, 325), (160, 330), (160, 330)])
    def capture(_):
        return next(seq)
    monkeypatch.setattr(mod, "capture_window", capture)
    clicks = []
    original = desktop.click
    def click(point):
        clicks.append(point)
        if len(clicks) == 1:
            host.fg = 88
        return original(point)
    monkeypatch.setattr(desktop, "click", click)
    loop = TributeLoop(desktop, clock=lambda: host.now, log=lambda _: None)
    assert loop.step("维修", lambda point: point)
    assert clicks == [(140, 325), (160, 330)]
    assert [xy for label, xy in host.inputs if label == "down"] == [(360, 630)]
