# Windows x64 离线安装包

从源码构建需要 Windows x64、Python 3.14 x64（带 Tcl/Tk）和 [NSIS 3.13](https://sourceforge.net/projects/nsis/files/NSIS%203/3.13/)。安装包的使用者不需要这些开发工具。

```powershell
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r '.\tools\build-requirements.txt'
& '.\.venv\Scripts\python.exe' '.\tools\build-setup.py' --makensis 'C:\Path\To\makensis.exe'
```

输出在 `dist\FoundationTributeRunner-<版本>-win-x64-setup.exe`，校验值在同目录的 `SHA256SUMS.txt`。请只将安装包与校验值上传到 Releases，不要提交 `dist` 或运行日志。

安装包用 LZMA 压缩，只打包此工作流及其实际依赖。OCR 使用 RapidOCR 随附的 PP-OCRv6 检测、识别模型与 ONNX Runtime CPU，不要求下载模型或安装 GPU 运行时。应用内附项目与第三方许可。

安装程序把应用写入 Program Files；启动器按普通权限打开，运行工作流时再按需请求 Windows UAC。没有使用从临时目录加载 DLL 的 PyInstaller 单文件模式，见 [PyInstaller 打包说明](https://www.pyinstaller.org/en/stable/operating-mode.html#how-the-one-file-program-works)。卸载可从 Windows「已安装的应用」执行，不会删除用户日志。

打包后可用新路径输出一次自检报告，不打开或操作游戏：

```powershell
$report = Join-Path $env:TEMP ('tribute-check-' + [guid]::NewGuid().ToString() + '.json')
$check = Start-Process '.\dist\FoundationTributeRunner\FoundationTributeRunner.exe' -ArgumentList ('--smoke-report "{0}"' -f $report) -WindowStyle Hidden -Wait -PassThru
Get-Content -LiteralPath $report -Encoding UTF8
$check.ExitCode
```
