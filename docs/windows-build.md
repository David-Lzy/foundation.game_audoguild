# Windows x64 离线安装包

从源码构建需要 Windows x64、Python 3.14 x64（带 Tcl/Tk）、Windows 自带的 .NET Framework C# 编译器和 [NSIS 3.13](https://sourceforge.net/projects/nsis/files/NSIS%203/3.13/)。安装包的使用者不需要另外安装开发工具。

```powershell
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r '.\tools\build-requirements.txt'
& '.\.venv\Scripts\python.exe' '.\tools\build-setup.py' --makensis 'C:\Path\To\makensis.exe'
```

输出在 `dist\FoundationTributeRunner-<版本>-win-x64-setup.exe`，校验值在同目录的 `SHA256SUMS.txt`。请只将安装包与校验值上传到 Releases，不要提交 `dist` 或运行日志。

安装包用 LZMA 压缩，只打包此工作流及其实际依赖。OCR 使用 RapidOCR 随附的 PP-OCRv6 检测、识别模型与 ONNX Runtime CPU，不要求下载模型或安装 GPU 运行时。应用内附项目与第三方许可。

安装程序默认使用 Program Files，也可以选择本地 NTFS 磁盘上的新目录，例如 `D:\Foundation Tribute Runner`。由于工作进程可能请求 Windows UAC，安装目录必须受管理员权限保护。安装器会拒绝普通用户可修改的目录、网络位置、目录链接和非空的无关目录；它不会更改已有文件夹的权限。

覆盖升级沿用原目录和之前的桌面快捷方式选择；要改路径，先卸载旧版再安装。开始菜单快捷方式始终创建；安装时可以额外勾选公用桌面快捷方式。卸载仅移除安装器记录的软件文件和快捷方式，不删除用户日志。

启动器按普通权限打开，没有使用从临时目录加载 DLL 的 PyInstaller 单文件模式，见 [PyInstaller 打包说明](https://www.pyinstaller.org/en/stable/operating-mode.html#how-the-one-file-program-works)。

打包后可用新路径输出一次自检报告，不打开或操作游戏：

```powershell
$report = Join-Path $env:TEMP ('tribute-check-' + [guid]::NewGuid().ToString() + '.json')
$check = Start-Process '.\dist\FoundationTributeRunner\FoundationTributeRunner.exe' -ArgumentList ('--smoke-report "{0}"' -f $report) -WindowStyle Hidden -Wait -PassThru
Get-Content -LiteralPath $report -Encoding UTF8
$check.ExitCode
```
