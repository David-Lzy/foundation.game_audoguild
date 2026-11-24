from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from itertools import zip_longest
import os
from pathlib import Path
import tempfile
from typing import Any, Protocol

import numpy as np
from PIL import Image


CropBox = tuple[int, int, int, int]


class OcrUnavailableError(RuntimeError):
    """Raised when optional OCR dependencies are not installed."""


@dataclass(frozen=True)
class OcrText:
    text: str
    confidence: float | None = None
    box: list[list[float]] | None = None

    def with_offset(self, x: int, y: int) -> "OcrText":
        if self.box is None:
            return self
        return OcrText(
            text=self.text,
            confidence=self.confidence,
            box=[[point[0] + x, point[1] + y] for point in self.box],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "box": self.box,
        }


class OcrAdapter(Protocol):
    def recognize(self, image: Image.Image, text_score: float | None = None) -> list[OcrText]:
        ...


class RapidOcrAdapter:
    def __init__(self) -> None:
        try:
            rapidocr = import_module("rapidocr")
            rapid_ocr_cls = rapidocr.RapidOCR
        except ImportError as exc:
            raise OcrUnavailableError(
                "OCR support is optional. Install it with "
                "`python -m pip install -e .[ocr]` in the project environment."
            ) from exc

        try:
            self._engine = rapid_ocr_cls()
        except ImportError as exc:
            raise OcrUnavailableError(
                "OCR support is optional and RapidOCR needs an inference backend. "
                "Install it with `python -m pip install -e .[ocr]` in the project environment."
            ) from exc

    def recognize(self, image: Image.Image, text_score: float | None = None) -> list[OcrText]:
        array = np.asarray(image.convert("RGB"))
        kwargs = {"text_score": text_score} if text_score is not None else {}
        result = self._engine(array, **kwargs)
        return normalize_rapidocr_output(result)


class PaddleOcrV6MediumAdapter:
    backend_name = "paddleocr-v6-medium"

    def __init__(self) -> None:
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_default_paddlex_cache_dir()))
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        # Paddle 3.3.x can fail on CPU oneDNN/PIR conversion for OCR detection.
        os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")
        try:
            paddleocr = import_module("paddleocr")
            paddle_ocr_cls = paddleocr.PaddleOCR
        except ImportError as exc:
            raise OcrUnavailableError(
                "PP-OCRv6 medium support is optional. Install it with "
                "`python -m pip install -e .[ocr]` in the project environment."
            ) from exc

        try:
            self._engine = paddle_ocr_cls(
                text_detection_model_name="PP-OCRv6_medium_det",
                text_recognition_model_name="PP-OCRv6_medium_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
            )
        except (ImportError, RuntimeError) as exc:
            raise OcrUnavailableError(
                "PP-OCRv6 medium support needs PaddleOCR and PaddlePaddle runtime. "
                "Install it with `python -m pip install -e .[ocr]` in the project environment."
            ) from exc

    def recognize(self, image: Image.Image, text_score: float | None = None) -> list[OcrText]:
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            image.convert("RGB").save(tmp_path)
            kwargs = {"text_rec_score_thresh": text_score} if text_score is not None else {}
            result = self._engine.predict(str(tmp_path), **kwargs)
            return normalize_paddleocr_output(result)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)


def create_default_ocr_adapter() -> OcrAdapter:
    backend = os.environ.get("FOUNDATION_OCR_BACKEND", "paddleocr-v6-medium").strip().lower()
    return _create_default_ocr_adapter_cached(backend)


def _default_paddlex_cache_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "artifacts" / "cache" / "paddlex"


@lru_cache(maxsize=4)
def _create_default_ocr_adapter_cached(backend: str) -> OcrAdapter:
    if backend in {"paddle", "paddleocr", "paddleocr-v6", "paddleocr-v6-medium", "pp-ocrv6-medium"}:
        return PaddleOcrV6MediumAdapter()
    if backend in {"rapid", "rapidocr", "rapidocr-v4"}:
        return RapidOcrAdapter()
    raise ValueError(
        "Unknown OCR backend. Use FOUNDATION_OCR_BACKEND=paddleocr-v6-medium or rapidocr."
    )


def parse_pixel_crop(value: str, image_size: tuple[int, int] | None = None) -> CropBox:
    parts = _parse_crop_numbers(value, cast=int)
    left, top, width, height = parts
    if width <= 0 or height <= 0:
        raise ValueError("Crop width and height must be positive.")
    return _clamp_crop((left, top, left + width, top + height), image_size)


def parse_normalized_crop(value: str, image_size: tuple[int, int]) -> CropBox:
    left, top, width, height = _parse_crop_numbers(value, cast=float)
    if not all(0.0 <= item <= 1.0 for item in (left, top, width, height)):
        raise ValueError("Normalized crop values must be between 0 and 1.")
    if width <= 0 or height <= 0:
        raise ValueError("Normalized crop width and height must be positive.")
    image_width, image_height = image_size
    box = (
        round(left * image_width),
        round(top * image_height),
        round((left + width) * image_width),
        round((top + height) * image_height),
    )
    return _clamp_crop(box, image_size)


def recognize_text(
    image: Image.Image,
    *,
    crop_box: CropBox | None = None,
    full_screen: bool = False,
    text_score: float | None = None,
    adapter: OcrAdapter | None = None,
) -> dict[str, Any]:
    if crop_box is not None and full_screen:
        raise ValueError("Use either a crop or full_screen, not both.")
    if crop_box is None and not full_screen:
        raise ValueError("OCR requires a crop by default. Pass --crop/--normalized-crop, or use --full-screen.")

    if full_screen:
        crop_box = (0, 0, image.width, image.height)
    assert crop_box is not None

    left, top, right, bottom = _clamp_crop(crop_box, image.size)
    cropped = image.crop((left, top, right, bottom))
    ocr = adapter or create_default_ocr_adapter()
    items = [item.with_offset(left, top) for item in ocr.recognize(cropped, text_score=text_score)]

    return {
        "crop_box": [left, top, right, bottom],
        "crop_size": [cropped.width, cropped.height],
        "text": "\n".join(item.text for item in items),
        "items": [item.as_dict() for item in items],
    }


def normalize_rapidocr_output(result: Any) -> list[OcrText]:
    legacy = _normalize_legacy_result(result)
    if legacy is not None:
        return legacy

    texts = getattr(result, "txts", None)
    if texts is None:
        return []

    scores = getattr(result, "scores", None)
    boxes = getattr(result, "boxes", None)
    if scores is None:
        scores = []
    if boxes is None:
        boxes = []
    items = []
    for box, text, score in zip_longest(boxes, texts, scores):
        if text is None:
            continue
        items.append(OcrText(text=str(text), confidence=_float_or_none(score), box=_box_or_none(box)))
    return items


def normalize_paddleocr_output(result: Any) -> list[OcrText]:
    if not result:
        return []
    first = result[0] if isinstance(result, list) else result
    payload = first
    if isinstance(first, dict) and "res" in first and isinstance(first["res"], dict):
        payload = first["res"]
    elif isinstance(first, dict) and "rec_texts" not in first:
        nested = first.get("json")
        if isinstance(nested, dict) and isinstance(nested.get("res"), dict):
            payload = nested["res"]

    if not isinstance(payload, dict):
        return []

    texts = payload.get("rec_texts") or []
    scores = payload.get("rec_scores") or []
    boxes = payload.get("rec_polys") or payload.get("dt_polys") or payload.get("rec_boxes") or []
    items = []
    for box, text, score in zip_longest(boxes, texts, scores):
        if text is None:
            continue
        items.append(OcrText(text=str(text), confidence=_float_or_none(score), box=_box_or_none(box)))
    return items


def _normalize_legacy_result(result: Any) -> list[OcrText] | None:
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], list):
        result = result[0]
    if not isinstance(result, list):
        return None

    items = []
    for row in result:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        box, text, score = row[0], row[1], row[2]
        items.append(OcrText(text=str(text), confidence=_float_or_none(score), box=_box_or_none(box)))
    return items


def _parse_crop_numbers(value: str, *, cast: type[int] | type[float]) -> tuple[Any, Any, Any, Any]:
    pieces = [piece.strip() for piece in value.split(",") if piece.strip()]
    if len(pieces) != 4:
        raise ValueError("Crop must contain four comma-separated values: left,top,width,height.")
    try:
        return tuple(cast(piece) for piece in pieces)  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError("Crop values must be numeric.") from exc


def _clamp_crop(crop_box: CropBox, image_size: tuple[int, int] | None) -> CropBox:
    left, top, right, bottom = crop_box
    if right <= left or bottom <= top:
        raise ValueError("Crop must have a positive width and height.")
    if image_size is None:
        return crop_box
    width, height = image_size
    if left < 0 or top < 0 or right > width or bottom > height:
        raise ValueError(f"Crop {list(crop_box)} is outside image bounds {list(image_size)}.")
    return crop_box


def _box_or_none(box: Any) -> list[list[float]] | None:
    if box is None:
        return None
    if hasattr(box, "tolist"):
        box = box.tolist()
    try:
        return [[float(point[0]), float(point[1])] for point in box]
    except (TypeError, ValueError, IndexError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
