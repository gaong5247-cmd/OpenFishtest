<#
Pin a trusted local Stockless executable as the 3000-Elo reference.

Example:
  $env:OPENFISHTEST_ADMIN_TOKEN = 'YOUR_PRIVATE_SECRET'
  .\scripts\Pin-Stockless.ps1 -EnginePath 'C:\Engines\Stockless.exe' -Version 'v0.7-Windows'

For the Linux-only quarantined arena the reference MUST be a Linux x86_64
ELF with an exact matching SHA, not a Windows executable.
#>
param(
    [Parameter(Mandatory = $true)][string]$EnginePath,
    [string]$Version = 'v0.7',
    [string]$Api = 'http://127.0.0.1:8000',
    [switch]$ForceRepin
)
$ErrorActionPreference = 'Stop'
$token = $env:OPENFISHTEST_ADMIN_TOKEN
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "Set OPENFISHTEST_ADMIN_TOKEN before this script."
}
if (-not (Test-Path -LiteralPath $EnginePath -PathType Leaf)) {
    throw "Stockless executable not found: $EnginePath"
}
$origin = $Api.TrimEnd('/')
if (-not ($origin -eq 'http://127.0.0.1:8000' -or
           $origin -eq 'http://localhost:8000' -or
           $origin.StartsWith('https://'))) {
    throw "Refusing to send administrator credentials over public plaintext HTTP."
}
$sha = (Get-FileHash -LiteralPath $EnginePath -Algorithm SHA256).Hash.ToLowerInvariant()
$headers = @{ 'X-Admin-Token' = $token }
$health = Invoke-RestMethod -Method Get -Uri "$origin/api/health"
Write-Host "Actual executable SHA-256: $sha"
$engines = Invoke-RestMethod -Uri "$origin/api/admin/engines" -Headers $headers
$found = $engines | Where-Object {
    $_.name -eq 'Stockless' -and $_.version -eq $Version -and $_.sha256 -eq $sha
} | Select-Object -First 1

if ($found) {
    $engineId = [int]$found.id
    Write-Host "Exact Stockless build already registered as ID $engineId"
} else {
    $payload = @{
        name = 'Stockless'
        version = $Version
        sha256 = $sha
        source_url = 'https://github.com/gaong5247-cmd/Stockless/releases/tag/Stockless_v0.7'
    } | ConvertTo-Json -Compress
    $created = Invoke-RestMethod -Uri "$origin/api/admin/engines" -Method Post -Headers $headers -ContentType 'application/json' -Body $payload
    $engineId = [int]$created.id
    Write-Host "Registered Stockless build as ID $engineId"
}
if ($health.reference_ready -and -not $ForceRepin) {
    Write-Host "Reference already pinned. Use -ForceRepin to explicitly switch it."
    exit 0
}
$pinJson = @{ engine_id = $engineId } | ConvertTo-Json -Compress
$pin = Invoke-RestMethod -Uri "$origin/api/admin/reference" -Method Post -Headers $headers -ContentType 'application/json' -Body $pinJson
Write-Host "PINNED Stockless reference ID $($pin.reference_engine_id)"
Write-Host "Relative rating baseline: $($pin.rating_anchor)"
Write-Host "Linux arena requires matching approved ELF and opening book."
