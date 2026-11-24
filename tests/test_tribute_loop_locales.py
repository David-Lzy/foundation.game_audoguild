from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from foundation_assistant.games import get_profile
from foundation_assistant.tribute_cycle import CycleOptions, CycleRunner, LiveCycleGame
from foundation_assistant.tribute_loop import TributeLoop
from foundation_assistant.tribute_loop_vision import Box, Frame, SIZE, is_tribute_victory, mail_age_upper
from foundation_assistant.vision.ocr import OcrText


class PanelReplay(Frame):
    """Project real template locations and screen-space OCR boxes without desktop input."""

    def __init__(self, assets: Path, labels=(), blocks=(), templates=()):
        image = Image.new("RGB", SIZE, "#223548")
        for rect, color in blocks:
            ImageDraw.Draw(image).rectangle(rect, fill=color)
        for name, position in templates:
            with Image.open(assets / (name + ".png")) as template:
                image.paste(template, position)
        super().__init__(image, assets, reader=self)
        self.labels = labels

    def crop(self, box: Box):
        self.last_box = box
        return super().crop(box)

    def read(self, _image, *, line=False):
        x0, y0, x1, y1 = self.last_box
        matches = []
        for value, (left, top, right, bottom) in self.labels:
            if x0 <= left < right <= x1 and y0 <= top < bottom <= y1:
                dx, dy = max(0, x0), max(0, y0)
                matches.append(OcrText(value, 0.99, [[left-dx, top-dy], [right-dx, top-dy],
                                                     [right-dx, bottom-dy], [left-dx, bottom-dy]]))
        return matches if not line or len(matches) == 1 else []


class EnglishRunReplay:
    def __init__(self, completion="repair_icon"):
        self.assets = get_profile().templates_dir
        self.completion = completion
        self.state = "map"
        self.ap = 273
        self.level = 2
        self.actions = []
        self.now = 0.0
        self.submitted = None
        self.repaired = False

    def refill(self, *, resource="Action Points", item="AP Potion", button="Use", quantity="× 1"):
        return PanelReplay(self.assets, [
            ("GET MORE", (897, 183, 1023, 217)), (resource, (827, 255, 986, 292)),
            (f"{self.ap}/300", (827, 306, 898, 329)), (item, (800, 397, 893, 423)),
            (quantity, (991, 398, 1030, 422)), (button, (1109, 414, 1160, 449)),
            ("Use", (1109, 534, 1160, 567)),  # A later row must not be substituted.
        ], templates=[("tribute_loop/refill_close", (1173, 176))])

    def target(self, *, vessel="Tribute Vessel", level="Lv. 3", ap="30", color="#a14539"):
        return PanelReplay(self.assets, [
            (vessel, (861, 569, 1027, 598)), (level, (861, 606, 934, 627)),
            ("Rally", (913, 897, 968, 920)), (ap, (937, 924, 971, 946)),
        ], blocks=[((780, 894, 1103, 947), color)])

    def setup(self, *, heading="Fleet Rating", ap="30", color="#ffdd76"):
        return PanelReplay(self.assets, [
            (heading, (582, 158, 716, 188)), ("Rally Time", (583, 232, 693, 258)),
            ("RALLY", (745, 837, 815, 861)), (ap, (780, 862, 812, 882)),
        ], blocks=[((590, 830, 968, 888), color)])

    def frame(self):
        if self.state == "map":
            icons = [("tribute_loop/map_avatar", (13, 18)), ("tribute_loop/map_search", (1865, 723)),
                     ("tribute_loop/map_mail", (1858, 877))]
            if (self.completion == "repair_icon" and self.submitted is not None and
                    self.now - self.submitted >= 1.5 and not self.repaired):
                icons.append(("tribute_loop/map_quick_repair", (122, 304)))
            return PanelReplay(self.assets, templates=icons)
        if self.state == "profile":
            return PanelReplay(self.assets, [(f"{self.ap}/300", (728, 27, 791, 46))], templates=[
                ("tribute_loop/profile_meter", (693, 27)), ("tribute_loop/profile_plus", (828, 27)),
                ("profile_close_button", (1170, 40)),
            ])
        if self.state == "refill":
            return self.refill()
        if self.state in {"search", "selected"}:
            return PanelReplay(self.assets, [
                ("Tribute Vessel", (985, 425, 1138, 449)), (str(self.level), (943, 587, 972, 639)),
                ("SEARCH", (909, 897, 1012, 929)),
            ], blocks=[((971, 409, 1150, 464), "#e4eadb" if self.state == "selected" else "#afbaad"),
                       ((770, 880, 1150, 943), "#ffdd76")],
                templates=[("tribute_loop/search_header_en", (908, 348))])
        if self.state == "target":
            return self.target()
        if self.state == "setup":
            return self.setup()
        if self.state == "mail":
            return PanelReplay(self.assets, [
                ("MAIL", (920, 16, 1002, 54)), ("Hunt", (626, 97, 681, 125)),
                ("Rallied Battle Victory", (710, 167, 999, 201)),
                ("The Rallied Troop of [G]'s Captain defeated a Lvl 3Tribute", (709, 205, 1256, 229)),
                ("Active 0 m(s) ago", (710, 243, 865, 268)),
            ], blocks=[((594, 128, 609, 140), "#e4eadb")], templates=[("mail_back_button", (555, 15))])
        raise AssertionError(self.state)

    def pause(self, seconds):
        self.now += seconds

    def click(self, point):
        view = self.frame()
        if self.state == "map" and point == view.map_avatar():
            self.state = "profile"
        elif self.state == "map" and point == view.map_search():
            self.actions.append("search-open")
            self.state = "search"
        elif self.state == "map" and point == view.map_mail():
            self.actions.append("mail")
            self.state = "mail"
        elif self.state == "map" and point == (145, 327):
            self.actions.append("repair")
            self.repaired = True
        elif self.state == "profile" and point == view.profile_close():
            self.state = "map"
        elif self.state == "profile" and point == view.profile()[0]:
            self.state = "refill"
        elif self.state == "refill" and point == (1007, 409):
            self.actions.append("refill")
            self.ap = 303
        elif self.state == "refill" and point == view.refill()[1]:
            self.state = "profile"
        elif self.state == "search" and point == (1062, 435):
            self.actions.append("tribute-tab")
            self.state = "selected"
        elif self.state == "selected" and point == (960, 913):
            self.actions.append("search")
            self.state = "target"
        elif self.state == "target" and point == (940, 908):
            self.actions.append("red-rally")
            self.state = "setup"
        elif self.state == "setup" and point == (780, 849):
            self.actions.append("yellow-rally")
            self.state = "map"
            self.ap -= 30
            self.submitted = self.now
        elif self.state == "mail" and point == view.mail_back():
            self.state = "map"
        else:
            pytest.fail(f"unexpected {self.state} click at {point}")

    def drag(self, start, end):
        assert self.state == "selected" and start == (960, 614) and end[1] < start[1]
        self.actions.append("level-drag")
        self.level += 1


@pytest.mark.parametrize("completion", ["repair_icon", "victory_mail"])
def test_english_client_one_count_workflow_replay(completion):
    game = EnglishRunReplay(completion)
    log = []
    clock = lambda: game.now
    emit = lambda event, **fields: log.append((event, fields))
    loop = TributeLoop(game, clock=clock, log=lambda _: None)
    runner = CycleRunner(LiveCycleGame(loop, emit), CycleOptions("Captain", total_rallies=1),
                         emit=emit, finish_requested=lambda: False, clock=clock)
    summary = runner.run()
    assert summary.reason == "count_limit"
    assert (summary.rallies, summary.refills, summary.ap) == (1, 1, 273)
    assert summary.repairs == (1 if completion == "repair_icon" else 0)
    assert dict(log)["round_confirmed"]["completion"] == completion
    assert game.actions[:7] == ["refill", "search-open", "tribute-tab", "level-drag", "search", "red-rally", "yellow-rally"]
    assert game.actions[7:] == (["repair"] if completion == "repair_icon" else ["mail", "mail"])
    assert game.state == "map"


def test_english_rally_controls_fail_closed_on_wrong_type_level_cost_or_color():
    probe = EnglishRunReplay()
    assert probe.target().target_rally(3) == (940, 908)
    assert probe.target(vessel="Ascendancy Minion").target_rally(3) is None
    assert probe.target(level="Lv. 13").target_rally(3) is None
    assert probe.target(ap="50").target_rally(3) is None
    assert probe.target(color="#ffdd76").target_rally(3) is None
    assert probe.setup().setup_rally() == (780, 849)
    assert probe.setup(heading="Fleet Details").setup_rally() is None
    assert probe.setup(ap="50").setup_rally() is None
    assert probe.setup(color="#a14539").setup_rally() is None


def test_english_target_rally_reads_digits_without_misreading_lvl_prefix():
    assets = get_profile().templates_dir
    def card(number):
        return PanelReplay(assets, [(number, (1260, 622, 1289, 638))],
                           blocks=[((1135, 906, 1461, 962), "#a14539")], templates=[
                               ("tribute_loop/target_title_en", (1225, 579)),
                               ("tribute_loop/target_rally_en", (1265, 908)),
                           ])
    assert card("2").target_rally(2) == (1299, 935)
    assert card("12").target_rally(2) is None
    assert card("12").target_rally(12) == (1299, 935)


def test_english_refill_only_accepts_the_first_owned_potion_bulk_control():
    probe = EnglishRunReplay()
    assert probe.refill().refill()[2] == (1007, 409)
    assert probe.refill(resource="Resources").refill() is None
    assert probe.refill(item="100 Action Points", button="Purchase").refill()[2] is None
    assert probe.refill(button="Purchase").refill()[2] is None
    assert probe.refill(quantity="500").refill()[2] is None


def test_english_labels_can_join_adjacent_ocr_words_but_not_separate_rows():
    replay = PanelReplay(get_profile().templates_dir, [
        ("AP", (790, 394, 830, 420)), ("Potion", (837, 394, 927, 418)),
        ("Action", (810, 254, 892, 287)), ("Points", (895, 284, 980, 315)),
    ])
    assert replay._label((775, 373, 947, 435), "appotion").center == (858, 407)
    assert replay._label((801, 233, 990, 330), "actionpoints") is None


def test_live_english_ap_heading_with_overlapping_detection_boxes():
    replay = PanelReplay(get_profile().templates_dir, [
        ("Action", (822, 253, 928, 290)), ("Point", (908, 253, 1004, 290)),
    ])
    assert replay._label((810, 235, 1065, 299), "actionpoint") is not None


@pytest.mark.parametrize(("value", "expected"), [
    ("Active 1 m(s) ago", 120), ("Active 12 s(s) ago", 13), ("Active 4 h(s) ago", None),
    ("2 minutes ago", 180), ("21分鐘前", 1320),
])
def test_localized_conservative_report_age(value, expected):
    assert mail_age_upper(value) == expected


@pytest.mark.parametrize(("description", "matched"), [
    ("The Rallied Troop of [G]'s Captain defeated a Lvl 3Tribute Vessel!", True),
    ("The Rallied Troop of [G]'s Captain defeated a Lvl 3Tribute …", True),
    ("The Rallied Troop of [G]'s Captain defeated a Lvl 30 Tribute", False),
    ("The Rallied Troop of [Captain]'s Other defeated a Lvl 3Tribute Vessel", False),
    ("The Rallied Troop of [G]'s Captain defeated a Lvl 3Tribute Object", False),
    ("The Rallied Troop of [G]'s Captain defeated a Lvl 3 Ascendancy Minion", False),
])
def test_english_report_matches_exact_leader_and_defeated_target(description, matched):
    assert is_tribute_victory("Rallied Battle Victory", description, "Captain", 3) is matched
