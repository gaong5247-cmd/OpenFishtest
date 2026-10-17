$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Python virtual environment not found: $python" }
if (-not $env:OPENFISHTEST_DATA) {
    $env:OPENFISHTEST_DATA = Join-Path $root 'data'
}
Push-Location $root
try {
    & $python (Join-Path $root 'archive.py') --apply
    if ($LASTEXITCODE -ne 0) { throw "PGN archive failed with exit code $LASTEXITCODE" }
}
finally { Pop-Location }
