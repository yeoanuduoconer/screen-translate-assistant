$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Run scripts\setup.ps1 first to create the project virtual environment.'
}
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$env:PADDLE_PDX_CACHE_HOME = Join-Path $projectRoot '.cache\paddlex'
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
& $python -m screen_translator
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
