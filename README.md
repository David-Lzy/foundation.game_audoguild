# 贡品船循环 / Tribute Vessel Runner

A Windows tool for the **Traditional Chinese and English** clients of Foundation: Galactic Frontier. This standalone repository includes the Tribute Vessel workflow and its runtime dependencies, not the other FoundationAssistant workflows.

脚本把游戏客户区调整为 1920×1080，按需使用已有药水，核对贡品船等级并发起集结，按新扳手或新战报确认结算，最后按设置维修。支持定时、总次数上限和持续运行，不会购买道具。

## Setup / 安装

In a PowerShell window opened in this repository:

```powershell
python -m venv .venv-tribute
& '.\.venv-tribute\Scripts\python.exe' -m pip install -e .
.\tools\tribute-ui.cmd
```

1. Open the game and return to the star map. Use either Traditional Chinese or English in the game's **Text Language** settings.
2. Fill in the in-game nickname without its alliance tag. Pick a vessel level that is searchable in the current star system, then set the batch size and stop mode.
3. Use **Preview settings** to review the numbers and **Start** to run. The launcher language is separate from the game language.

要手动操作游戏，请先用 **F9** 正常收尾或 **F8** 急停。运行中游戏失去焦点时，脚本会在键鼠空闲后尝试拉回前台。正式运行会消耗已有体力、药水和维修模组。请先查看游戏条款。

See [使用说明 / Full usage](docs/tribute-loop.md) for the no-spend previews, hotkeys, and count-limit behavior.

License: GPL-3.0-or-later. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
