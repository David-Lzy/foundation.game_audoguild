"""Windows display-language selection and Traditional Chinese display text."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache


SIMPLIFIED = "zh-Hans"
TRADITIONAL = "zh-Hant"
ENGLISH = "en"
LANGUAGES = (SIMPLIFIED, TRADITIONAL, ENGLISH)
LANGUAGE_LABELS = ("简体中文", "繁體中文", "English")

_MUI_LANGUAGE_NAME = 0x00000008
_LCMAP_TRADITIONAL_CHINESE = 0x04000000


def windows_display_language() -> str:
    """Read the primary Windows UI language, not regional formats or keyboard layout."""
    try:
        get_languages = ctypes.windll.kernel32.GetUserPreferredUILanguages
        get_languages.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.ULONG),
                                  wintypes.LPWSTR, ctypes.POINTER(wintypes.ULONG))
        get_languages.restype = wintypes.BOOL
        count, size = wintypes.ULONG(), wintypes.ULONG()
        if not get_languages(_MUI_LANGUAGE_NAME, ctypes.byref(count), None, ctypes.byref(size)) or not size.value:
            return ""
        languages = ctypes.create_unicode_buffer(size.value)
        if get_languages(_MUI_LANGUAGE_NAME, ctypes.byref(count), languages, ctypes.byref(size)):
            return languages.value  # First name in the null-separated preferred list.
    except (AttributeError, OSError):
        pass
    return ""


def launcher_language(windows_tag: str | None) -> str:
    parts = (windows_tag or "").strip().lower().replace("_", "-").split("-")
    if parts[0] != "zh":
        return ENGLISH
    qualifiers = set(parts[1:])
    if qualifiers & {"hant", "cht"}:
        return TRADITIONAL
    if qualifiers & {"hans", "chs"}:
        return SIMPLIFIED
    return TRADITIONAL if qualifiers & {"tw", "hk", "mo"} else SIMPLIFIED


@lru_cache(maxsize=512)
def traditional_text(source: str) -> str:
    """Map launcher templates and visible worker messages without changing the raw log."""
    if not source:
        return source
    try:
        map_text = ctypes.windll.kernel32.LCMapStringEx
        map_text.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, ctypes.c_int,
                             wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.LPARAM)
        map_text.restype = ctypes.c_int
        args = ("zh-TW", _LCMAP_TRADITIONAL_CHINESE, source, -1)
        size = map_text(*args, None, 0, None, None, 0)
        if size:
            buffer = ctypes.create_unicode_buffer(size)
            if map_text(*args, buffer, size, None, None, 0):
                source = buffer.value
    except (AttributeError, OSError):
        pass
    # Prefer common Traditional UI terms over literal character conversions.
    for literal, ui_term in (("游戲", "遊戲"), ("運行", "執行"), ("設置", "設定"),
                             ("窗口", "視窗"), ("日志", "日誌"), ("鼠標", "滑鼠")):
        source = source.replace(literal, ui_term)
    return source
