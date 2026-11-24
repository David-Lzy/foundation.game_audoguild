from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class TemplateMatch:
    score: float
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    def as_dict(self) -> dict[str, object]:
        center_x, center_y = self.center
        return {
            "score": round(self.score, 5),
            "rect": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
            },
            "center": [center_x, center_y],
        }


def _to_bgr(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def match_template(
    screenshot: Image.Image,
    template_path: str | Path,
    *,
    threshold: float = 0.86,
) -> TemplateMatch | None:
    match = best_template_match(screenshot, template_path)
    if match.score < threshold:
        return None
    return match


def find_template_matches(
    screenshot: Image.Image,
    template_path: str | Path,
    *,
    threshold: float = 0.86,
    limit: int = 20,
    overlap_threshold: float = 0.3,
) -> list[TemplateMatch]:
    template = _read_template(template_path)
    source = _to_bgr(screenshot)
    if template.shape[0] > source.shape[0] or template.shape[1] > source.shape[1]:
        raise ValueError("Template is larger than screenshot/search region")

    result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
    height, width = template.shape[:2]
    y_coords, x_coords = np.where(result >= threshold)
    candidates = [
        TemplateMatch(float(result[y, x]), int(x), int(y), width, height)
        for y, x in zip(y_coords, x_coords)
    ]
    candidates.sort(key=lambda item: item.score, reverse=True)

    selected: list[TemplateMatch] = []
    for candidate in candidates:
        if all(_intersection_over_union(candidate, kept) <= overlap_threshold for kept in selected):
            selected.append(candidate)
            if len(selected) >= limit:
                break
    return selected


def best_template_match(
    screenshot: Image.Image,
    template_path: str | Path,
) -> TemplateMatch:
    template = _read_template(template_path)
    source = _to_bgr(screenshot)
    if template.shape[0] > source.shape[0] or template.shape[1] > source.shape[1]:
        raise ValueError("Template is larger than screenshot/search region")
    result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
    _, max_value, _, max_location = cv2.minMaxLoc(result)
    height, width = template.shape[:2]
    return TemplateMatch(float(max_value), int(max_location[0]), int(max_location[1]), width, height)


def _read_template(template_path: str | Path) -> np.ndarray:
    template = cv2.imdecode(np.fromfile(str(template_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if template is None:
        raise ValueError(f"Could not read template: {template_path}")
    return template


def _intersection_over_union(left: TemplateMatch, right: TemplateMatch) -> float:
    left_x2 = left.x + left.width
    left_y2 = left.y + left.height
    right_x2 = right.x + right.width
    right_y2 = right.y + right.height
    inter_left = max(left.x, right.x)
    inter_top = max(left.y, right.y)
    inter_right = min(left_x2, right_x2)
    inter_bottom = min(left_y2, right_y2)
    inter_width = max(0, inter_right - inter_left)
    inter_height = max(0, inter_bottom - inter_top)
    intersection = inter_width * inter_height
    if intersection == 0:
        return 0.0
    left_area = left.width * left.height
    right_area = right.width * right.height
    return intersection / max(1, left_area + right_area - intersection)
