"""Guarded 1080p recognition for Traditional Chinese and English Tribute screens."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path
import re
from typing import Callable
import unicodedata

import cv2
import numpy as np
from PIL import Image

from foundation_assistant.vision.ocr import OcrText, normalize_rapidocr_output
from foundation_assistant.vision.template import TemplateMatch


SIZE = (1920, 1080)
RALLY_COST = 30
Point = tuple[int, int]
Box = tuple[int, int, int, int]
EN_TRIBUTE_LABELS = {"tributevessel", "trbutevessel", "tributevesel"}  # Narrow OCR variants of the tab text.
EN_VICTORY_TITLES = {"ralliedbattlevictory", "rallyvictory"}
EN_LEVEL = r"(?:level|lvl?)[.:]?([1-9][0-9]?)"


@dataclass(frozen=True)
class RepairView:
    """An unobscured star map, with or without the fleet's quick-repair control."""

    button: Point | None


def offset(point: Point, box: Box) -> Box:
    x, y = point
    left, top, right, bottom = box
    return x + left, y + top, x + right, y + bottom


def compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def level_number(text: str) -> int | None:
    text = compact(text)
    match = re.search(r"(?:等[級级]|level|lvl?)[.:]?([1-9][0-9]?)(?![0-9])", text)
    if match is None:
        match = re.search(r"(?<![0-9])([1-9][0-9]?)[級级](?:的)?[貢贡]品", text)
    return int(match[1]) if match else None


def points_number(text: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"([0-9]{1,4})/([0-9]{1,4})", compact(text))
    if match:
        current, total = map(int, match.groups())
        if 1 <= total <= 1000 and current <= 1000:
            return current, total
    return None


def mail_age_upper(text: str) -> int | None:
    """Conservative upper bound; the displayed minute is not a timestamp."""
    value = compact(text)
    if value in {"剛剛", "刚刚", "justnow", "momentsago"}:
        return 60
    # The English client's mail list prints e.g. "Active 4 h(s) ago".
    # Only accept minutes and seconds; hours, dates, etc. never establish freshness.
    match = re.fullmatch(r"(?:active)?([0-9]{1,3})(分鐘|分钟|分|秒鐘|秒钟|秒|"
                         r"minutes?|mins|(?:min|m)(?:\(s\))?|seconds?|secs|(?:sec|s)(?:\(s\))?)(?:前|ago)", value)
    if match:
        unit = 60 if match[2].startswith(("分", "m")) else 1
        return (int(match[1]) + 1) * unit
    return None


def is_tribute_victory(title: str, description: str, captain: str, level: int) -> bool:
    title = compact(title)
    detail = compact(description)
    if not (
        title in EN_VICTORY_TITLES
        or re.fullmatch(r"集[結结](?:作[戰战]|[戰战][鬥斗])?(?:[勝胜]利|[獲获][勝胜])", title)
    ):
        return False
    # Match the actual leader, not a guild tag or a name elsewhere in a report.
    name = compact(captain)
    detail_with_spaces = unicodedata.normalize("NFKC", description).casefold()
    untagged = re.sub(r"\[[^\]]+\](?:['’]s)?|【[^】]+】", "", detail_with_spaces)
    if title in EN_VICTORY_TITLES:
        leader = re.match(r"\s*(?:the\s+)?(?:rallied\s+troop|rally)\s+of\s+(.+?)\s+(?:has\s+)?defeated\b(.*)", untagged)
        if not name or leader is None or compact(leader[1]) != name:
            return False
        # The list can truncate the target after "Tribute". Match the level
        # of the defeated vessel, not a level token on the leader's side.
        target = re.fullmatch(rf"(?:a|the)?{EN_LEVEL}tribute(?:vessel)?[.!…]*", compact(leader[2]))
        return target is not None and int(target[1]) == level
    if not re.search(r"[貢贡]品", detail) or level_number(detail) != level:
        return False
    leader = re.split(r"[擊击][敗败]|[戰战][勝胜]", compact(untagged), maxsplit=1)
    if not name or len(leader) != 2:
        return False
    return re.fullmatch(rf"(?:恭喜!?|由)?{re.escape(name)}(?:所)?(?:的|已|成功|所|[發发]起|"
                        r"[率帶带][領领]|集[結结]|[部艦舰][隊队]|[隊队]伍)*", leader[0]) is not None


class TextReader:
    def __init__(self) -> None:
        from rapidocr import RapidOCR

        self.engine = RapidOCR(params={
            "Global.log_level": "error",
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        })

    def read(self, image: np.ndarray, *, line: bool = False) -> list[OcrText]:
        return normalize_rapidocr_output(self.engine(image, use_det=not line, use_cls=False, text_score=0.78))


@lru_cache(maxsize=40)
def _template(path: Path) -> np.ndarray:
    with Image.open(path) as source:
        return cv2.cvtColor(np.asarray(source.convert("RGB")), cv2.COLOR_RGB2BGR)


class Frame:
    def __init__(self, image: Image.Image, templates: Path, reader: TextReader | None = None) -> None:
        if image.size != SIZE:
            raise ValueError(f"Expected a 1920×1080 client screenshot, got {image.size}")
        self.bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        self.templates = templates
        self.reader = reader

    def crop(self, box: Box) -> np.ndarray:
        x0, y0, x1, y1 = box
        return self.bgr[max(0, y0):min(SIZE[1], max(0, y1)), max(0, x0):min(SIZE[0], max(0, x1))]

    def match(self, name: str, box: Box, threshold: float = 0.86, *, shared: bool = False,
              top_rows: int | None = None) -> TemplateMatch | None:
        area = self.crop(box)
        needle = _template(self.templates / ("" if shared else "tribute_loop") / f"{name}.png")
        if top_rows is not None:
            needle = needle[:top_rows]
        height, width = needle.shape[:2]
        if area.shape[0] < height or area.shape[1] < width:
            return None
        scores = cv2.matchTemplate(area, needle, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score < threshold:
            return None
        return TemplateMatch(score, x + max(0, box[0]), y + max(0, box[1]), width, height)

    def line(self, box: Box) -> str:
        crop = self.crop(box)
        if self.reader is None or crop.size == 0:
            return ""
        image = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        texts = self.reader.read(image, line=True)
        if len(texts) == 1 and (texts[0].confidence or 0) >= 0.80:
            return texts[0].text.strip()
        return ""

    def _read_labels(self, box: Box, accept: Callable[[str], bool]) -> list[tuple[str, TemplateMatch]]:
        """Read exact normalized tokens and bind each to its own position in this frame."""
        area = self.crop(box)
        if self.reader is None or not area.size:
            return []
        labels = []
        for item in self.reader.read(area):
            value = compact(item.text)
            score = item.confidence or 0.0
            if score < 0.83 or not item.box or not accept(value):
                continue
            xs, ys = zip(*item.box)
            left, right = round(min(xs)), round(max(xs))
            top, bottom = round(min(ys)), round(max(ys))
            if 0 <= left < right <= area.shape[1] and 0 <= top < bottom <= area.shape[0]:
                labels.append((value, TemplateMatch(score, max(0, box[0]) + left, max(0, box[1]) + top,
                                                    right - left, bottom - top)))
        return labels

    def _label(self, box: Box, *values: str) -> TemplateMatch | None:
        words = self._read_labels(box, lambda _: True)
        allowed = set(values)
        matches = [word for value, word in words if value in allowed]
        if not matches:
            # The detector sometimes splits "AP Potion" or "Fleet Rating"
            # into two boxes. Only combine neighbors on the same text line.
            for first_text, first in words:
                for second_text, second in words:
                    if first_text + second_text not in allowed or first.x >= second.x:
                        continue
                    height = min(first.height, second.height)
                    gap = second.x - (first.x + first.width)
                    # RapidOCR adds padding; in the actual English AP dialog
                    # the two word boxes overlap by 20 px at a height of 37.
                    if not (-0.62 * height <= gap <= 0.72 * height and
                            abs(first.center[1] - second.center[1]) <= 0.36 * height):
                        continue
                    top = min(first.y, second.y)
                    bottom = max(first.y + first.height, second.y + second.height)
                    matches.append(TemplateMatch(min(first.score, second.score), first.x, top,
                                                 second.x + second.width - first.x, bottom - top))
        return matches[0] if len(matches) == 1 else None

    def _colored_button(self, point: Point, *, gold: bool) -> bool:
        # Check both sides of the label, away from text and separate from the
        # cost line. This rejects Rally text on unrelated surfaces.
        for left, right in ((-79, -62), (62, 79)):
            patch = self.crop(offset(point, (left, -5, right, 5))).astype(np.int16)
            if patch.size == 0:
                return False
            b, g, r = np.moveaxis(patch, -1, 0)
            mask = ((r >= 188) & (g >= 147) & (r > g) & (g - b >= 47) if gold
                    else (r >= 111) & (g < 142) & (r - g >= 37) & (r - b >= 30))
            if np.mean(mask) < 0.82:
                return False
        return True

    def _english_rally_buttons(self, box: Box, *, gold: bool) -> list[Point]:
        cost_text = str(RALLY_COST)
        labels = self._read_labels(box, {"rally", cost_text}.__contains__)
        costs = [match.center for text, match in labels if text == cost_text]
        return [match.center for text, match in labels if text == "rally"
                and any(-9 <= cx - match.center[0] <= 54 and 14 <= cy - match.center[1] <= 43 for cx, cy in costs)
                and self._colored_button(match.center, gold=gold)]

    def map_search(self) -> Point | None:
        match = self.match("map_search", (1810, 640, 1920, 826), 0.84)
        return match.center if match else None

    def map_mail(self) -> Point | None:
        match = self.match("map_mail", (1810, 830, 1920, 973), 0.83)
        return match.center if match else None

    def map_avatar(self) -> Point | None:
        match = self.match("map_avatar", (0, 0, 112, 106), 0.88)
        return match.center if match else None

    def repair_view(self) -> RepairView | None:
        search = self.map_search()
        if search is None or self.map_avatar() is None or self.search_header() is not None:
            return None
        if self._glyph_light(search) < 135:
            return None  # Matching a dimmed map through a modal is not enough.
        region = (109, 260, 218, 442)
        candidates = [self.match(name, region, 0.88) for name in ("map_quick_repair", "map_quick_repair_legacy")]
        best = max((match for match in candidates if match), key=lambda match: match.score, default=None)
        if best is None:
            return RepairView(None)
        patch = self.crop(offset(best.center, (-14, -14, 14, 14)))
        gold_tone = np.median(patch[:, :, 2]) - np.median(patch[:, :, 0])
        if gold_tone < 23 or self._glyph_light(best.center) < 153:
            return None  # Never treat an obscured/disabled control as an enabled one.
        return RepairView(best.center)

    def _glyph_light(self, point: Point) -> float:
        pixels = self.crop(offset(point, (-14, -14, 14, 14)))
        return float(np.percentile(np.min(pixels, axis=2), 90))

    def quick_repair_toast(self) -> bool:
        if self.reader is None:
            return False
        for text in self.reader.read(self.crop((600, 185, 1430, 415))):
            value = compact(text.text)
            if (text.confidence or 0) >= 0.78 and (
                re.search(r"快捷[維维]修.*消耗.*[維维]修模[組组]", value)
                or re.search(r"quickrepair.*(?:consum(?:e[ds]?|ing)|used|costs?).*repairmodules?", value)
            ):
                return True
        return False

    @cached_property
    def _search_heading(self) -> tuple[TemplateMatch | None, bool]:
        box = (800, 265, 1120, 450)
        zh = self.match("search_header", box, 0.89)
        return (zh, False) if zh else (self.match("search_header_en", box, 0.88), True)

    def search_header(self) -> TemplateMatch | None:
        return self._search_heading[0]

    def search_tab(self, *, selected: bool = False) -> Point | None:
        header, english = self._search_heading
        if header is None:
            return None
        if english:
            text = compact(self.line(offset(header.center, (19, 45, 200, 99)))).replace(":", "")
            if text not in EN_TRIBUTE_LABELS:
                return None
            x, y = header.center
            center = (x + 102, y + 70)
        else:
            tab = self.match("tribute_tab", offset(header.center, (33, 40, 181, 106)), 0.86)
            if tab is None:
                return None
            center = tab.center
        if selected:
            inset = (-85, -7, -77, 7) if english else (-64, -7, -51, 7)
            background = self.crop(offset(center, inset))
            if not background.size or np.median(background) < 211:
                return None
        return center

    def level_picker(self) -> tuple[int, Point] | None:
        header, english = self._search_heading
        if header is None or self.search_tab(selected=True) is None:
            return None
        x, y = header.center
        box = (x - 40, y + 211, x + 42, y + 285) if english else (x - 28, y + 222, x + 28, y + 279)
        text = compact(self.line(box))
        if re.fullmatch(r"[1-9][0-9]?", text):
            return int(text), (x, y + 249)
        return None

    def search_button(self, level: int) -> Point | None:
        header, english = self._search_heading
        picker = self.level_picker()
        if header is None or picker is None or picker[0] != level:
            return None
        if english:
            button = self._label(offset(header.center, (-126, 508, 126, 583)), "search")
            return button.center if button and self._colored_button(button.center, gold=True) else None
        button = self.match("search_button", offset(header.center, (-130, 470, 130, 595)), 0.89)
        return button.center if button else None

    def target_rally(self, level: int) -> Point | None:
        rally = self.match("target_rally", (100, 285, 1890, 1050), 0.89)
        if rally is not None:
            title = self.match("target_title", offset(rally.center, (-171, -405, 55, -113)), 0.89)
            if title is not None:
                text = self.line(offset(title.center, (-44, 17, 68, 51)))
                return rally.center if level_number(text) == level else None
        return self._english_target_rally(level)

    def _english_target_rally(self, level: int) -> Point | None:
        rally = self.match("target_rally_en", (100, 285, 1890, 1050), 0.90)
        if rally is not None and self._colored_button(rally.center, gold=False):
            title = self.match("target_title_en", offset(rally.center, (-158, -410, 171, -142)), 0.91)
            if title is not None:
                # The real English client renders "Lvl 2", whose lowercase l
                # RapidOCR sometimes reads as the digit 1. Read only the number
                # after the label and keep enough width for both digits.
                number = compact(self.line(offset((title.x, title.y), (32, 32, 92, 72))))
                return rally.center if re.fullmatch(r"[1-9][0-9]?", number) and int(number) == level else None
        candidates = []
        for button in self._english_rally_buttons((100, 285, 1890, 1050), gold=False):
            title = self._label(offset(button, (-158, -410, 171, -142)), "tributevessel")
            if title is None:
                continue
            # The English title is wider than the Chinese one; the level stays
            # in the line just below its left edge, not below the title center.
            number = self.line(offset((title.x, title.y + title.height), (-5, 0, 143, 48)))
            match = re.fullmatch(EN_LEVEL, compact(number))
            if match and int(match[1]) == level:
                candidates.append(button)
        return candidates[0] if len(candidates) == 1 else None

    def setup_rally(self) -> Point | None:
        header = self.match("setup_title", (98, 17, 1440, 438), 0.89)
        if header is not None:
            button = self.match("setup_rally", offset(header.center, (38, 535, 285, 691)), 0.90)
            if button is not None:
                return button.center
        return self._english_setup_rally()

    def _english_setup_rally(self) -> Point | None:
        header = self._label((98, 17, 1440, 438), "fleetrating")
        if header is None:
            return None
        if self._label(offset((header.x, header.y), (-8, 43, 258, 155)), "rallytime") is None:
            return None
        buttons = self._english_rally_buttons(offset((header.x, header.y), (0, 474, 407, 784)), gold=True)
        return buttons[0] if len(buttons) == 1 else None

    def profile(self) -> tuple[Point, tuple[int, int] | None] | None:
        meter = self.match("profile_meter", (645, 9, 885, 99), 0.89)
        if meter is None:
            return None
        plus = self.match("profile_plus", offset(meter.center, (117, -24, 196, 24)), 0.88)
        if plus is None:
            return None
        text = self.line(offset(meter.center, (18, -21, 117, 6)))
        return plus.center, points_number(text)

    def profile_close(self) -> Point | None:
        if self.profile() is None:
            return None
        region = (1150, 25, 1280, 128)
        match = self.match("profile_close_button", region, 0.88, shared=True)
        if match is None:
            # The global announcement strip can overlap just the bottom of
            # the X. Recognize and click the visible part, above the strip.
            match = self.match("profile_close_button", region, 0.94, shared=True, top_rows=34)
        return match.center if match else None

    def profile_captain(self) -> str | None:
        if self.profile_close() is None:
            return None
        text = self.line((805, 168, 1017, 204))
        return text if text and 1 <= len(text) <= 26 and any(c.isalnum() for c in text) else None

    def refill(self) -> tuple[tuple[int, int] | None, Point, Point | None] | None:
        title = self.match("refill_title", (760, 105, 1160, 335), 0.90)
        english = title is None
        if english:
            title = self._label((817, 130, 1101, 280), "getmore")
        if title is None:
            return None
        x, y = title.center
        close = self.match("refill_close", offset(title.center, (184, -37, 283, 36)), 0.89)
        if close is None:
            return None
        points = points_number(self.line((x - 133, y + 101, x - 38, y + 136)))
        if english:
            if self._label(offset(title.center, (-150, 36, 105, 100)), "actionpoint", "actionpoints") is None:
                return None  # Other "GET MORE" dialogs aren't the AP dialog.
            label = self._label(offset(title.center, (-184, 175, -18, 236)), "appotion", "actionpotion")
            use = self._label(offset(title.center, (115, 187, 244, 267)), "use")
        else:
            label = self.match("refill_potion", offset(title.center, (-184, 183, -50, 260)), 0.89)
            use = self.match("refill_use", offset(title.center, (129, 195, 223, 264)), 0.89)
        bulk = None
        if label and use:
            # Only the left-of-Use recommended-quantity control in row one.
            quantity = compact(self.line((x + 15, y + 194, x + 84, y + 226)))
            if re.fullmatch(r"[×x*][1-9][0-9]{0,2}", quantity):
                bulk = (x + 47, y + 209)
        return points, close.center, bulk

    def mail_back(self) -> Point | None:
        title = compact(self.line((839, 5, 1081, 63)))
        if title not in {"mail", "郵件", "邮件", "信件"}:
            return None
        back = self.match("mail_back_button", (525, 0, 700, 81), 0.85, shared=True)
        return back.center if back else None

    def mail(self) -> tuple[Point, Point, bool] | None:
        back = self.mail_back()
        if back is None:
            return None
        tab = compact(self.line((595, 90, 711, 127)))
        if tab not in {"hunt", "巡獵", "巡猎", "狩獵", "狩猎", "獵殺", "猎杀", "獵捕", "猎捕"}:
            return None
        # Read below the global gold announcement strip. In-between colors
        # are transitions, not evidence that the tab is unselected.
        shade = np.median(self.crop((594, 129, 608, 139)))
        if 80 < shade < 193:
            return None
        return back, (653, 109), bool(shade >= 193)

    def fresh_victory(self, captain: str, level: int, elapsed_seconds: float) -> bool:
        if self.reader is None:
            return False
        # The first four rows of the Hunt list. Evaluate each title, summary,
        # and age separately so different rows cannot supply each other's proof.
        for row in range(4):
            y = 155 + row * 135
            # Skip non-victory rows before OCRing their longer summaries.
            title = self.line((708, y + 11, 1304, y + 49))
            if not re.search(r"victory|[勝胜]利|[獲获][勝胜]", compact(title)):
                continue
            age = mail_age_upper(self.line((710, y + 83, 1020, y + 116)))
            if age is None or age >= elapsed_seconds:
                continue
            description = self.line((708, y + 47, 1310, y + 76))
            if is_tribute_victory(title, description, captain, level):
                return True
        return False
