$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv-tribute\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Tribute environment not found. See docs/tribute-loop.md for setup.'
}

& $python -X utf8 -m foundation_assistant tribute-loop @args
exit $LASTEXITCODE
