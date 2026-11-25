from __future__ import annotations

import argparse

from PIL import Image
import pytest

from foundation_assistant import tribute_loop as mod
from foundation_assistant.games import get_profile
from foundation_assistant.tribute_loop_vision import Frame, SIZE, is_tribute_victory, mail_age_upper, points_number
from foundation_assistant.win.window import GameWindow, Rect


class MockFrame:
    def __init__(self, io):
        self.io = io
        self.state = io.state

    def map_search(self):
        return (1880, 740) if self.state == "map" else None

    def map_mail(self):
        return (1880, 888) if self.state == "map" else None

    def map_avatar(self):
        return (44, 45) if self.state == "map" else None

    def search_header(self):
        return True if self.state in ("other", "tribute") else None

    def search_tab(self, selected=False):
        return (1060, 432) if self.state == "tribute" or (not selected and self.state == "other") else None

    def level_picker(self):
        return (self.io.level, (960, 614)) if self.state == "tribute" else None

    def search_button(self, level):
        return (960, 912) if self.state == "tribute" and self.io.level == level else None

    def target_rally(self, level):
        return (1000, 700) if self.state == "target" and self.io.level == level else None

    def setup_rally(self):
        return (620, 900) if self.state == "setup" else None

    def mail(self):
        return ((600, 30), (653, 109), self.io.selected) if self.state == "mail" else None

    def mail_back(self):
        return (600, 30) if self.state == "mail" else None

    def fresh_victory(self, captain, level, elapsed_seconds):
        self.io.result_ages.append(elapsed_seconds)
        return captain == "Captain" and level == self.io.level and self.io.victory and elapsed_seconds > 181

    def profile(self):
        return ((1180, 677), (self.io.ap, 300)) if self.state == "profile" else None

    def profile_close(self):
        return (1290, 201) if self.state == "profile" else None

    def profile_captain(self):
        return "Captain" if self.state == "profile" else None

    def refill(self):
        if self.state == "refill":
            return (self.io.ap, 300), (1196, 195), (1004, 405) if self.io.bulk else None
        return None


class MockDesktop:
    def __init__(self, monkeypatch):
        monkeypatch.setattr(mod, "Frame", MockFrame)
        self.now = 0.0
        self.state = "map"
        self.level = 1
        self.ap = 21
        self.level_stuck = False
        self.bulk = True
        self.fill_to = 300
        self.victory = True
        self.selected = False
        self.clicks = []
        self.final_submits = []
        self.result_ages = []
        self.drags = []

    def session(self):
        return mod.TributeLoop(self, clock=lambda: self.now, log=lambda _: None)

    def frame(self):
        return MockFrame(self)

    def pause(self, seconds):
        self.now += seconds

    def click(self, point):
        self.clicks.append(point)
        path = {
            ("map", (1880, 740)): "other",
            ("other", (1060, 432)): "tribute",
            ("tribute", (960, 912)): "target",
            ("target", (1000, 700)): "setup",
            ("setup", (620, 900)): "map",
            ("map", (1880, 888)): "mail",
            ("mail", (653, 109)): "mail",
            ("mail", (600, 30)): "map",
            ("map", (44, 45)): "profile",
            ("profile", (1180, 677)): "refill",
            ("refill", (1004, 405)): "refill",
            ("refill", (1196, 195)): "profile",
            ("profile", (1290, 201)): "map",
        }
        if (self.state, point) == ("setup", (620, 900)):
            self.final_submits.append(self.now)
            self.ap -= mod.AP_COST
        if self.state == "mail" and point == (653, 109):
            self.selected = True
        if self.state == "refill" and point == (1004, 405):
            self.ap = self.fill_to
        self.state = path[(self.state, point)]

    def drag(self, start, end):
        assert self.state == "tribute"
        self.drags.append((start, end))
        if not self.level_stuck:
            self.level += 1 if end[1] < start[1] else -1


def test_dry_run_defaults_to_three_without_taking_window(monkeypatch, capsys):
    parser = argparse.ArgumentParser()
    mod.add_parser(parser.add_subparsers())
    args = parser.parse_args(["tribute-loop"])
    monkeypatch.setattr(mod, "prepare_window", lambda _: pytest.fail("dry-run touched window"))
    assert args.func(args) == 0
    assert args.level == 3
    assert "180" in capsys.readouterr().out


def test_preview_drags_and_searches_without_clicking_rally(monkeypatch):
    io = MockDesktop(monkeypatch)
    assert io.session().start(3, preview=True) is None
    assert io.level == 3 and len(io.drags) == 2
    assert io.clicks == [(1880, 740), (1060, 432), (960, 912)]


def test_can_drag_down_towards_lower_level(monkeypatch):
    io = MockDesktop(monkeypatch)
    io.level = 5
    io.session().start(3, preview=True)
    assert io.level == 3
    assert len(io.drags) == 2
    assert all(end[1] > start[1] for start, end in io.drags)


def test_out_of_range_level_never_searches(monkeypatch):
    io = MockDesktop(monkeypatch)
    io.level_stuck = True
    with pytest.raises(mod.Stop, match="无法调到 3"):
        io.session().start(3, preview=False)
    assert (960, 912) not in io.clicks


def test_full_loop_waits_180_then_requires_result_for_next_round(monkeypatch):
    io = MockDesktop(monkeypatch)
    io.session().run(captain="Captain", level=3, rounds=2, result_timeout=250, auto_refill=True)
    assert len(io.final_submits) == 2
    assert io.final_submits[1] - io.final_submits[0] >= 195
    assert all(seconds >= 180 for seconds in io.result_ages)
    assert io.clicks.count((1004, 405)) == 1
    assert io.ap == 240


def test_missing_result_stops_after_one_rally(monkeypatch):
    io = MockDesktop(monkeypatch)
    io.victory = False
    with pytest.raises(mod.Stop, match="未确认本轮新战报"):
        io.session().run(captain="Captain", level=3, rounds=0, result_timeout=190, auto_refill=False)
    assert len(io.final_submits) == 1 and io.result_ages == pytest.approx([180.65])
    assert io.clicks.count((1000, 700)) == 1


def test_detects_captain_before_start_when_not_provided(monkeypatch):
    io = MockDesktop(monkeypatch)
    io.session().run(captain="", level=3, rounds=1, result_timeout=220, auto_refill=False)
    assert io.clicks[:3] == [(44, 45), (1290, 201), (1880, 740)]
    assert len(io.final_submits) == 1


def test_preview_refill_never_uses_potions(monkeypatch):
    io = MockDesktop(monkeypatch)
    io.session().refill(preview=True)
    assert io.clicks == [(44, 45), (1180, 677)]
    assert io.ap == 21


def test_already_full_refill_does_not_click_plus_or_potions(monkeypatch):
    io = MockDesktop(monkeypatch)
    io.ap = 300
    io.session().refill(preview=False)
    assert io.clicks == [(44, 45), (1290, 201)]


def test_refill_no_matching_first_row_never_falls_back_to_purchase(monkeypatch):
    io = MockDesktop(monkeypatch)
    io.bulk = False
    with pytest.raises(mod.Stop, match="没用药水"):
        io.session().refill(preview=False)
    assert io.clicks == [(44, 45), (1180, 677)]


def test_refill_no_verified_full_capacity_does_not_repeat(monkeypatch):
    io = MockDesktop(monkeypatch)
    io.fill_to = 121
    with pytest.raises(mod.Stop, match="体力已加满"):
        io.session().refill(preview=False)
    assert io.clicks.count((1004, 405)) == 1 and io.ap == 121


def test_refill_cancelled_at_click_does_not_use_potion(monkeypatch):
    io = MockDesktop(monkeypatch)
    permissions = iter((True, True, False))
    assert not io.session().refill(preview=False, allow_use=lambda: next(permissions))
    assert io.ap == 21 and (1004, 405) not in io.clicks
    assert io.state == "map"


@pytest.mark.parametrize(("title", "detail", "valid"), [
    ("Rallied Battle Victory", "The Rallied Troop of [G]'s Captain defeated a Lvl 3Tribute", True),
    ("集結勝利", "[G]Captain的集結部隊擊敗了等級3貢品船", True),
    ("集結戰鬥勝利", "由[G]Captain發起的集結擊敗了3級貢品船", True),
    ("集結作戰勝利", "[G]Captain集結隊伍戰勝等級3貢品船！", True),
    ("Rallied Battle Victory", "The Rallied Troop of [Captain]'s Other defeated Lvl 3Tribute", False),
    ("Rallied Battle Victory", "The Rallied Troop of [G]'s Captain2 defeated a Lvl 3Tribute", False),
    ("集結勝利", "[G]Captain的集結部隊擊敗了等級13貢品船", False),
    ("集結勝利", "[G]Captain的集結部隊擊敗了等級3爪牙", False),
    ("集結失敗", "[G]Captain的集結部隊擊敗了等級3貢品船", False),
])
def test_report_checks_title_owner_target_and_level(title, detail, valid):
    assert is_tribute_victory(title, detail, "Captain", 3) is valid


def test_age_is_conservative_and_ap_capacity_is_parsed():
    assert mail_age_upper("1m ago") == 120
    assert mail_age_upper("２分鐘前") == 180
    assert mail_age_upper("剛剛") == 60
    assert mail_age_upper("Active 9h ago") is None
    assert points_number("８７ ／ ３００") == (87, 300)
    assert points_number("87/0") is None


def test_moving_target_waits_for_two_matching_positions_before_clicking():
    frames = iter([(890, 620), None, (948, 618), (962, 619), (965, 620)])
    clicks = []
    now = [0.0]

    class PanningMap:
        def frame(self):
            return next(frames)

        def pause(self, seconds):
            now[0] += seconds

        click = staticmethod(clicks.append)

    loop = mod.TributeLoop(PanningMap(), clock=lambda: now[0])
    assert loop.step("target", lambda position: position, timeout=3, stabilize=True)
    assert clicks == [(965, 620)]


@pytest.mark.parametrize("is_map", [True, False])
def test_only_visible_map_is_retryable_if_setup_did_not_open(is_map):
    class Screen:
        def frame(self):
            return self

        def setup_rally(self):
            return None

        def repair_view(self):
            return object() if is_map else None

    loop = mod.TributeLoop(Screen(), clock=lambda: 0)
    with pytest.raises(mod.Stop) as error:
        loop.wait_for_rally_setup(timeout=0)
    assert isinstance(error.value, mod.RallySetupNotOpened) is is_map


@pytest.mark.parametrize("is_map", [True, False])
def test_missing_red_target_is_only_recoverable_from_verified_map(monkeypatch, is_map):
    class Screen:
        def frame(self):
            return self

        def search_header(self):
            return True

        def search_tab(self, *, selected=False):
            return (1000, 430)

        def repair_view(self):
            return object() if is_map else None

    monkeypatch.setattr(mod, "Frame", Screen)
    loop = mod.TributeLoop(Screen(), clock=lambda: 0)
    monkeypatch.setattr(loop, "set_level", lambda _: None)
    stages = []

    def step(label, *_args, **_kwargs):
        stages.append(label)
        if "红色集结" in label:
            raise mod.ObservationTimeout("missing red target")

    monkeypatch.setattr(loop, "step", step)
    with pytest.raises(mod.Stop) as error:
        loop.start(3, preview=False)
    assert isinstance(error.value, mod.RallyTargetNotFound) is is_map
    assert len(stages) == 2 and "红色集结" in stages[-1]


def test_1080p_required_and_button_templates_are_packaged():
    profile = get_profile()
    with pytest.raises(ValueError, match="1920×1080"):
        Frame(Image.new("RGB", (2560, 1600)), profile.templates_dir)
    img = Image.new("RGB", SIZE, "#182840")
    with Image.open(profile.templates_dir / "tribute_loop" / "map_search.png") as template:
        img.paste(template, (1860, 720))
    frame = Frame(img, profile.templates_dir)
    assert frame.map_search() is not None
    assert frame.setup_rally() is None and frame.target_rally(3) is None


@pytest.mark.parametrize(("shade", "expected"), [(33, False), (106, None), (227, True)])
def test_mail_does_not_treat_intermediate_announcement_shade_as_unselected(monkeypatch, shade, expected):
    frame = Frame(Image.new("RGB", SIZE, (shade,) * 3), get_profile().templates_dir)
    monkeypatch.setattr(frame, "mail_back", lambda: (607, 36))
    monkeypatch.setattr(frame, "line", lambda _: "巡獵")
    page = frame.mail()
    assert (page[2] if page else None) is expected


def test_mail_back_remains_recognizable_when_tab_word_is_covered(monkeypatch):
    profile = get_profile()
    img = Image.new("RGB", SIZE, "#182840")
    with Image.open(profile.templates_dir / "mail_back_button.png") as template:
        img.paste(template, (555, 15))
    frame = Frame(img, profile.templates_dir)
    monkeypatch.setattr(frame, "line", lambda box: "郵件" if box[1] == 5 else "巡")
    assert frame.mail_back() is not None
    assert frame.mail() is None


def test_profile_x_can_be_closed_above_an_announcement_covering_its_bottom():
    assets = get_profile().templates_dir
    image = Image.new("RGB", SIZE, "#132a33")
    for name, position in (("tribute_loop/profile_meter", (693, 27)),
                           ("tribute_loop/profile_plus", (828, 27)), ("profile_close_button", (1192, 48))):
        with Image.open(assets / f"{name}.png") as template:
            image.paste(template, position)
    image.paste("#bb8c2e", (580, 82, 1400, 129))
    frame = Frame(image, assets)
    assert frame.match("profile_close_button", (1150, 25, 1280, 128), 0.88, shared=True) is None
    assert frame.profile_close() == (1216, 65)
    image.paste("#bb8c2e", (580, 46, 1400, 129))
    assert Frame(image, assets).profile_close() is None


def test_prepare_window_resizes_and_reads_back_actual_client(monkeypatch):
    profile = get_profile()
    prior = GameWindow(1, "game", 2, Rect(0, 0, 2560, 1600), Rect(0, 0, 2560, 1600))
    post = GameWindow(1, "game", 2, Rect(0, 0, 1990, 1130), Rect(20, 45, 1940, 1125))
    windows = iter([prior, post])
    monkeypatch.setattr(mod, "find_game_window", lambda *_: next(windows))
    monkeypatch.setattr(mod.win32gui, "GetWindowPlacement", lambda _: (0, 1))
    monkeypatch.setattr(mod.win32gui, "IsIconic", lambda _: False)
    monkeypatch.setattr(mod.win32api, "MonitorFromWindow", lambda *_: 3)
    monkeypatch.setattr(mod.win32api, "GetMonitorInfo", lambda _: {"Monitor": (0, 0, 2560, 1600)})
    calls = []
    monkeypatch.setattr(mod, "resize_client_area", lambda win, w, h, *, tolerance: calls.append((win, w, h, tolerance)) or {"applied": True})
    assert mod.prepare_window(profile) == post
    assert calls == [(prior, 1920, 1080, 0)]
