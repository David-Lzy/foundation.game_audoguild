from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageGrab
import win32con
import win32gui
import win32ui

from foundation_assistant.win.window import GameWindow, Rect


DEFAULT_BASE_SIZE = (1920, 1080)


@dataclass(frozen=True)
class ScreenshotMetadata:
    backend: str
    screen_rect: Rect
    client_size: tuple[int, int]
    image_size: tuple[int, int]
    base_size: tuple[int, int] = DEFAULT_BASE_SIZE

    @property
    def scale_x(self) -> float:
        return self.image_size[0] / self.base_size[0]

    @property
    def scale_y(self) -> float:
        return self.image_size[1] / self.base_size[1]

    def base_to_image(self, x: float, y: float) -> tuple[int, int]:
        return round(x * self.scale_x), round(y * self.scale_y)

    def image_to_base(self, x: float, y: float) -> tuple[int, int]:
        if self.scale_x == 0 or self.scale_y == 0:
            raise ValueError("Screenshot scale cannot be zero")
        return round(x / self.scale_x), round(y / self.scale_y)

    def image_to_screen(self, x: float, y: float) -> tuple[int, int]:
        return self.screen_rect.left + round(x), self.screen_rect.top + round(y)

    def as_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "screen_rect": self.screen_rect.__dict__,
            "client_size": list(self.client_size),
            "image_size": list(self.image_size),
            "base_size": list(self.base_size),
            "scale": [self.scale_x, self.scale_y],
        }


@dataclass(frozen=True)
class WindowScreenshot:
    image: Image.Image
    metadata: ScreenshotMetadata


def _capture_with_mss(screen_rect: Rect) -> Image.Image:
    import mss

    monitor = {
        "left": screen_rect.left,
        "top": screen_rect.top,
        "width": screen_rect.width,
        "height": screen_rect.height,
    }
    with mss.mss() as sct:
        shot = sct.grab(monitor)
    return Image.frombytes("RGB", shot.size, shot.rgb)


def _capture_with_imagegrab(screen_rect: Rect) -> Image.Image:
    return ImageGrab.grab(bbox=screen_rect.as_bbox()).convert("RGB")


def _capture_with_print_window(window: GameWindow) -> Image.Image | None:
    width = window.client_rect.width
    height = window.client_rect.height
    hwnd_dc = None
    mfc_dc = None
    save_dc = None
    bitmap = None
    try:
        hwnd_dc = win32gui.GetWindowDC(window.hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)
        result = ctypes.windll.user32.PrintWindow(window.hwnd, save_dc.GetSafeHdc(), 3)
        if not result:
            return None
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        image = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
        return image.convert("RGB")
    except Exception:
        return None
    finally:
        if bitmap is not None:
            win32gui.DeleteObject(bitmap.GetHandle())
        if save_dc is not None:
            save_dc.DeleteDC()
        if mfc_dc is not None:
            mfc_dc.DeleteDC()
        if hwnd_dc is not None:
            win32gui.ReleaseDC(window.hwnd, hwnd_dc)


def capture_window_with_metadata(
    window: GameWindow,
    out: str | Path | None = None,
    *,
    prefer_background: bool = False,
    base_size: tuple[int, int] = DEFAULT_BASE_SIZE,
) -> WindowScreenshot:
    backend = "mss"
    image = None
    if prefer_background:
        image = _capture_with_print_window(window)
        if image is not None:
            backend = "print_window"
    if image is None:
        try:
            image = _capture_with_mss(window.client_rect)
        except Exception:
            image = _capture_with_imagegrab(window.client_rect)
            backend = "imagegrab"
    image = image.convert("RGB")
    metadata = ScreenshotMetadata(
        backend=backend,
        screen_rect=window.client_rect,
        client_size=(window.client_rect.width, window.client_rect.height),
        image_size=image.size,
        base_size=base_size,
    )
    if out is not None:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
    return WindowScreenshot(image=image, metadata=metadata)


def capture_window(window: GameWindow, out: str | Path | None = None) -> Image.Image:
    return capture_window_with_metadata(window, out).image
