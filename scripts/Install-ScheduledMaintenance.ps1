param(
    [ValidateRange(15, 240)]
    [int]$PublishMinutes = 30,
    [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$ArchiveTime = '03:00'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "Run py -3 -m venv .venv and install requirements first: $python"
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI is missing. Install gh and run gh auth login first.'
}
$publishScript = Join-Path $PSScriptRoot 'Invoke-Publish.ps1'
$archiveScript = Join-Path $PSScriptRoot 'Invoke-Archive.ps1'
$publishCommand = 'powershell.exe -NoProfile -NonInteractive -File "{0}"' -f $publishScript
$archiveCommand = 'powershell.exe -NoProfile -NonInteractive -File "{0}"' -f $archiveScript

Write-Host "Registering tasks under the current Windows user account..."
Write-Host "Public snapshots every $PublishMinutes minutes; Releases PGN archive daily at $ArchiveTime."
Write-Host 'Each archive upload is checked before local PGNs are removed.'
& schtasks.exe /Create /F /TN 'OpenFishtest-Publish' /SC MINUTE /MO $PublishMinutes /TR $publishCommand
if ($LASTEXITCODE -ne 0) { throw 'Could not create publish task' }
& schtasks.exe /Create /F /TN 'OpenFishtest-Archive' /SC DAILY /ST $ArchiveTime /TR $archiveCommand
if ($LASTEXITCODE -ne 0) { throw 'Could not create archive task' }
Write-Host 'OpenFishtest scheduled maintenance tasks registered.'
Write-Host 'To remove them: schtasks /Delete /TN OpenFishtest-Publish /F'
Write-Host 'And: schtasks /Delete /TN OpenFishtest-Archive /F'
