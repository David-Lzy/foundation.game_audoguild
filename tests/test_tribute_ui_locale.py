from __future__ import annotations

import pytest

from foundation_assistant import tribute_ui as ui
from foundation_assistant.launcher_locale import ENGLISH, SIMPLIFIED, TRADITIONAL, launcher_language


@pytest.mark.parametrize(("display", "expected"), [
    ("zh-CN", SIMPLIFIED), ("zh-SG", SIMPLIFIED), ("zh-Hans", SIMPLIFIED),
    ("zh-Hans-HK", SIMPLIFIED), ("zh_CN", SIMPLIFIED),
    ("zh-TW", TRADITIONAL), ("zh-HK", TRADITIONAL), ("zh-MO", TRADITIONAL),
    ("zh-Hant", TRADITIONAL), ("zh-Hant-CN", TRADITIONAL),
    ("en-US", ENGLISH), ("fr-FR", ENGLISH), ("ja-JP", ENGLISH), (None, ENGLISH),
])
def test_only_windows_chinese_display_languages_default_to_chinese(display, expected):
    assert launcher_language(display) == expected


@pytest.fixture(scope="module")
def tk_root():
    try:
        window = ui.tk.Tk()
    except ui.tk.TclError as exc:
        pytest.skip(f"Tk desktop unavailable: {exc}")
    window.withdraw()
    try:
        yield window
    finally:
        window.destroy()


@pytest.fixture
def root(tk_root):
    # Reuse Tcl/Tk so creating five views does not reload the Tk scripts.
    window = ui.tk.Toplevel(tk_root)
    window.withdraw()
    try:
        yield window
    finally:
        window.destroy()


@pytest.mark.parametrize(("display", "language", "selection", "start"), [
    ("zh-CN", SIMPLIFIED, "简体中文", "开始运行"),
    ("zh-TW", TRADITIONAL, "繁體中文", "開始執行"),
    ("de-DE", ENGLISH, "English", "Start"),
])
def test_new_launcher_applies_default_selection_to_widgets(monkeypatch, root, display, language, selection, start):
    monkeypatch.setattr(ui, "windows_display_language", lambda: display)
    app = ui.TributeUI(root, captain="Test captain")
    assert app.lang == language
    assert tuple(app.lang_box["values"]) == ("简体中文", "繁體中文", "English")
    assert app.lang_box.get() == selection and app.run_button["text"] == start


def test_dropdown_translates_existing_status_and_log_without_changing_parameters(monkeypatch, root):
    monkeypatch.setattr(ui, "windows_display_language", lambda: "zh-CN")
    app = ui.TributeUI(root, captain="Test captain")
    app.mode.set("count")
    app.total_rallies.set("30")
    app.validate()
    app.events = [{"event": "detail", "detail": "游戏窗口已确认。"}, {"event": "round_confirmed", "rallies": 2}]
    app.lang_box.current(1)
    app._language()
    assert root.title() == "貢品船循環"
    assert "30 次" in app.status_text["text"]
    assert "遊戲視窗已確認。" in app.log.get("1.0", "end")
    assert "累計 2 次" in app.log.get("1.0", "end")
    assert app.events[0]["detail"] == "游戏窗口已确认。"
    app.lang_box.current(2)
    app._language()
    assert app.run_button["text"] == "Start"
    app.lang_box.current(0)
    app._language()
    assert app.run_button["text"] == "开始运行"
    assert app._settings().total_rallies == 30 and app.captain.get() == "Test captain"


def test_english_launch_flag_overrides_windows_display_language(monkeypatch, root):
    monkeypatch.setattr(ui, "windows_display_language", lambda: pytest.fail("explicit English should bypass detection"))
    app = ui.TributeUI(root, english=True)
    assert app.lang_box.get() == "English"


def test_hunt_retry_check_interval_preview_and_worker_arguments(root):
    app = ui.TributeUI(root, captain="Test captain", english=True)
    assert app.hunt_check["text"] == "Retry unreadable Hunt list"
    assert app.hunt_retry.get() and app.hunt_interval.get() == "5"
    assert not app.hunt_spin.instate(["disabled"])

    app.hunt_interval.set("2")
    args = app._settings().arguments()
    assert args[args.index("--hunt-retry-minutes") + 1] == "2"
    app.validate()
    assert "every 2 min" in app.status_text["text"]
    app.lang_box.current(1)
    app._language()
    assert "巡獵列表" in app.hunt_check["text"] and "2 分鐘" in app.status_text["text"]

    app.hunt_check.invoke()
    assert app.hunt_spin.instate(["disabled"])
    assert "--no-hunt-retry" in app._settings().arguments()
    app.validate()
    assert "不再重查" in app.status_text["text"]
    app.running = True
    app._run_controls()
    assert app.hunt_check.instate(["disabled"])
    app.running = False
    app._run_controls()
    assert not app.hunt_check.instate(["disabled"]) and app.hunt_spin.instate(["disabled"])
