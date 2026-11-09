param(
    [string]$PythonExe,
    [switch]$Dev,
    [ValidateSet('auto', 'modelscope', 'huggingface')]
    [string]$ModelSource = 'auto'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $projectRoot '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$checkPython = "import sys, sysconfig; sys.exit(0 if sys.version_info[:2] == (3, 11) and sysconfig.get_platform() == 'win-amd64' else 1)"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $pythonArguments = @()
    if (-not $PythonExe) {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) {
            try {
                & $launcher.Source -3.11 -c $checkPython 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $PythonExe = $launcher.Source
                    $pythonArguments = @('-3.11')
                }
            }
            catch {
                # The launcher can exist without a registered Python 3.11.
            }
        }
        if (-not $PythonExe) {
            $defaultPython = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $defaultPython) {
                throw 'Install Python 3.11 x64, or pass -PythonExe with the full path to python.exe.'
            }
            $PythonExe = $defaultPython.Source
        }
    }
    & $PythonExe @pythonArguments -c $checkPython
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 x64 is required. Pass -PythonExe if needed.' }
    & $PythonExe @pythonArguments -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
}

& $python -c $checkPython
if ($LASTEXITCODE -ne 0) { throw 'The existing .venv must use Python 3.11 x64.' }

$extras = if ($Dev) { '.[fast-ocr,dev]' } else { '.[fast-ocr]' }
Push-Location -LiteralPath $projectRoot
try {
    & $python -m pip install --editable $extras
    if ($LASTEXITCODE -ne 0) { throw 'Installing dependencies failed.' }
    & $python scripts\download_ocr_models.py --source $ModelSource
    if ($LASTEXITCODE -ne 0) { throw 'Downloading or verifying OCR models failed.' }
}
finally {
    Pop-Location
}
Write-Host 'Setup complete. Launch with scripts\run.ps1 or the .cmd file in the repository root.'
