@echo off
setlocal
set "PY=%~dp0..\.venv-tribute\Scripts\pythonw.exe"
if not exist "%PY%" (
    echo Tribute runtime missing. See docs\tribute-loop.md for setup.
    pause
    exit /b 1
)
pushd "%~dp0.."
start "" "%PY%" -m foundation_assistant.tribute_ui %*
popd
