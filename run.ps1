$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Missing .venv. Follow README.md to install the environment first.'
}
& $pythonPath (Join-Path $PSScriptRoot 'main.py') @args
exit $LASTEXITCODE
