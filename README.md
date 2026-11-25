# 贡品船循环 / Tribute Vessel Runner

A Windows tool for the **Traditional Chinese and English** clients of Foundation: Galactic Frontier. This standalone repository includes the Tribute Vessel workflow and its runtime dependencies, not the other FoundationAssistant workflows.

脚本把游戏客户区调整为 1920×1080，按需使用已有药水，核对贡品船等级并发起集结，按新扳手或新战报确认结算，最后按设置维修。支持定时、总次数上限和持续运行，不会购买道具。

## 下载 / Download

在 [GitHub Releases](https://github.com/David-Lzy/foundation.game_audoguild/releases/latest) 下载 `FoundationTributeRunner-*-win-x64-setup.exe`。这是 Windows 10/11 x64 的单文件离线安装包，内含 Python 运行时和 OCR 模型。可以选择安装路径，并按需勾选「创建桌面快捷方式」（新安装默认不勾选）。也可从开始菜单打开 **Foundation Tribute Runner**。安装需要管理员确认；启动界面不会操作游戏。

Download the single Windows x64 setup EXE from [GitHub Releases](https://github.com/David-Lzy/foundation.game_audoguild/releases/latest). It bundles Python and the OCR models. Choose the install folder and optionally create a desktop shortcut. The Start menu shortcut is always installed.

安装包目前没有代码签名。可用 `Get-FileHash -Algorithm SHA256` 与 Releases 的 `SHA256SUMS.txt` 核对下载。

## Run from source / 从源码运行

In a PowerShell window opened in this repository:

```powershell
python -m venv .venv-tribute
& '.\.venv-tribute\Scripts\python.exe' -m pip install -e .
.\tools\tribute-ui.cmd
```

1. Open the game and return to the star map. Use either Traditional Chinese or English in the game's **Text Language** settings.
2. Fill in the in-game nickname without its alliance tag. Pick a vessel level that is searchable in the current star system, then set the batch size and stop mode.
3. Use **Preview settings** to review the numbers and **Start** to run. The launcher offers Simplified Chinese, Traditional Chinese, and English and defaults to the matching Windows display language, or English for other languages. This does not change the game language.

要手动操作游戏，请先用 **F9** 正常收尾或 **F8** 急停。运行中游戏失去焦点时，脚本会在键鼠空闲后尝试拉回前台。正式运行会消耗已有体力、药水和维修模组。请先查看游戏条款。

See [使用说明 / Full usage](docs/tribute-loop.md) for the no-spend previews, hotkeys, and count-limit behavior, or [打包说明 / Build the installer](docs/windows-build.md) to build your own EXE.

License: GPL-3.0-or-later. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
