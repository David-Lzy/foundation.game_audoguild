from __future__ import annotations

from PIL import Image, ImageEnhance
import pytest

from foundation_assistant.games import get_profile
from foundation_assistant.tribute_loop import MAIL_FIRST_POLL, Stop, TributeLoop
from foundation_assistant.tribute_loop_vision import Frame, RepairView, SIZE


class RepairScreen:
    def __init__(self, view, *, feedback=False):
        self.view = view
        self.feedback = feedback

    def repair_view(self):
        return self.view

    def quick_repair_toast(self):
        return self.feedback


class IO:
    def __init__(self, before, *, after="clear"):
        self.now = 0.0
        self.before = before
        self.after = after
        self.clicked = []
        self.click_times = []

    def frame(self):
        if self.clicked and callable(self.after):
            return self.after(len(self.clicked), self.now)
        if self.clicked and self.after == "clear":
            return RepairScreen(RepairView(None))
        if self.clicked and self.after == "modal":
            return RepairScreen(None)
        return RepairScreen(self.before(self.now))

    def pause(self, seconds):
        self.now += seconds

    def click(self, point):
        self.clicked.append(point)
        self.click_times.append(self.now)

    def loop(self):
        return TributeLoop(self, log=lambda _: None, clock=lambda: self.now)


def test_new_wrench_ends_the_wait_without_waiting_for_mail_or_three_minutes(monkeypatch):
    io = IO(lambda t: RepairView((145, 327) if t >= 7 else None))
    loop = io.loop()
    monkeypatch.setattr(loop, "check_victory_mail", lambda *_: pytest.fail("new wrench should win before first mail poll"))
    assert loop.wait_battle_end("Captain", 3, 0, 480, repair_already_visible=False) == "repair_icon"
    assert 7 <= io.now < 10 and not io.clicked


@pytest.mark.parametrize("old", [True, False])
def test_persistent_wrench_does_not_count_as_new_even_if_not_seen_before_send(monkeypatch, old):
    io = IO(lambda _: RepairView((145, 327)))
    loop = io.loop()
    polls = []
    monkeypatch.setattr(loop, "check_victory_mail", lambda *_: polls.append(io.now) or True)
    assert loop.wait_battle_end("Captain", 3, 0, 480, repair_already_visible=old) == "victory_mail"
    assert len(polls) == 1 and MAIL_FIRST_POLL <= polls[0] < MAIL_FIRST_POLL + 1


def test_existing_wrench_cannot_become_fresh_after_flicker(monkeypatch):
    io = IO(lambda t: RepairView((145, 327) if t < 3 or t > 6 else None))
    loop = io.loop()
    monkeypatch.setattr(loop, "check_victory_mail", lambda *_: True)
    assert loop.wait_battle_end("Captain", 3, 0, 480, repair_already_visible=True) == "victory_mail"
    assert io.now >= MAIL_FIRST_POLL


def test_no_wrench_and_no_new_mail_does_not_start_the_next_round(monkeypatch):
    io = IO(lambda _: RepairView(None))
    loop = io.loop()
    monkeypatch.setattr(loop, "check_victory_mail", lambda *_: False)
    with pytest.raises(Stop, match="结算超时"):
        loop.wait_battle_end("Captain", 3, 0, 65, repair_already_visible=False)
    assert io.now == pytest.approx(65) and not io.clicked


def test_repair_clicks_only_once_and_requires_return_to_cleared_map():
    io = IO(lambda _: RepairView((145, 327)))
    assert io.loop().repair_fleet()
    assert io.clicked == [(145, 327)]


def test_unchanged_wrench_retries_once_after_wait_and_can_clear():
    io = IO(lambda _: RepairView((145, 327)), after=lambda clicks, _: RepairScreen(
        RepairView((145, 327) if clicks == 1 else None)))
    assert io.loop().repair_fleet()
    assert io.clicked == [(145, 327), (145, 327)]
    assert io.click_times[1] - io.click_times[0] >= 8


def test_unchanged_wrench_after_two_clicks_stops_without_a_third():
    io = IO(lambda _: RepairView((145, 327)), after="unchanged")
    with pytest.raises(Stop, match="已点两次.*扳手提示消失"):
        io.loop().repair_fleet()
    assert io.clicked == [(145, 327), (145, 327)]


@pytest.mark.parametrize("after", [
    "modal",
    lambda *_: RepairScreen(RepairView((145, 347))),
    lambda *_: RepairScreen(RepairView((145, 327)), feedback=True),
    lambda _, now: RepairScreen(RepairView(None if now < 0.5 else (145, 327))),
])
def test_modal_moved_wrench_feedback_or_transient_clear_blocks_retry(after):
    io = IO(lambda _: RepairView((145, 327)), after=after)
    with pytest.raises(Stop, match="扳手提示消失"):
        io.loop().repair_fleet()
    assert io.clicked == [(145, 327)]


def test_feedback_on_fresh_retry_frame_prevents_a_second_click():
    io = IO(lambda _: RepairView((145, 327)), after="unchanged")

    def log(message):
        if message.endswith("重试一次。"):
            io.after = lambda *_: RepairScreen(RepairView((145, 327)), feedback=True)

    loop = TributeLoop(io, log=log, clock=lambda: io.now)
    with pytest.raises(Stop, match="重试前画面已变化或出现维修反馈"):
        loop.repair_fleet()
    assert io.clicked == [(145, 327)]


def test_no_repair_button_on_valid_map_skips_after_a_short_probe():
    io = IO(lambda _: RepairView(None))
    assert not io.loop().repair_fleet()
    assert io.now == pytest.approx(3) and not io.clicked


def test_map_repair_vision_requires_real_map_controls_and_bright_gold_wrench():
    profile = get_profile()
    sample = Image.new("RGB", SIZE, "#203858")
    positions = {"map_avatar": (13, 18), "map_search": (1865, 723), "map_quick_repair": (122, 304)}
    assets = profile.templates_dir / "tribute_loop"
    for name, point in positions.items():
        with Image.open(assets / f"{name}.png") as template:
            sample.paste(template, point)
    assert Frame(sample, profile.templates_dir).repair_view() == RepairView((145, 327))
    assert Frame(ImageEnhance.Brightness(sample).enhance(0.45), profile.templates_dir).repair_view() is None
    sample.paste("#203858", (122, 304, 169, 351))
    assert Frame(sample, profile.templates_dir).repair_view() == RepairView(None)
