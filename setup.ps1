# Native Windows PowerShell 5.1+ installation; no admin rights required.
[CmdletBinding()]
param(
    [switch]$LoginAll,
    [switch]$Safe,
    [string]$ClaudeRoot = "",
    [string]$CodexRoot = ""
)
$ErrorActionPreference = 'Stop'

$PythonExe = $null
$PythonPrefix = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -c 'import sys; assert sys.version_info >= (3,9)' *> $null
    if ($LASTEXITCODE -eq 0) { $PythonExe = 'py'; $PythonPrefix = @('-3') }
}
if (-not $PythonExe -and (Get-Command python -ErrorAction SilentlyContinue)) {
    & python -c 'import sys; assert sys.version_info >= (3,9)' *> $null
    if ($LASTEXITCODE -eq 0) { $PythonExe = 'python' }
}
if (-not $PythonExe) {
    throw 'Python 3.9+ not found. Install from python.org or winget install Python.Python.3.13; reopen PowerShell.'
}

$AppRoot = Join-Path $HOME '.ai-cli-pool'
$AppDir = Join-Path $AppRoot 'app'
$BinDir = Join-Path $AppRoot 'bin'
New-Item -ItemType Directory -Path $AppDir,$BinDir -Force | Out-Null
$Installed = Join-Path $AppDir 'aifull.py'
Copy-Item (Join-Path $PSScriptRoot 'aifull.py') $Installed -Force

$Prefix = if ($PythonExe -eq 'py') { 'py -3' } else { 'python' }
foreach ($name in @('aifull','claudefull','codexfull')) {
    $provider = switch ($name) { 'claudefull' { 'claude' } 'codexfull' { 'codex' } default { '' } }
    $cmdText = "@echo off`r`n$Prefix `"%USERPROFILE%\.ai-cli-pool\app\aifull.py`" $provider %*`r`n"
    [IO.File]::WriteAllText((Join-Path $BinDir "$name.cmd"), $cmdText, [Text.Encoding]::ASCII)
}

$OldUserPath = [Environment]::GetEnvironmentVariable('Path','User')
$PathEntries = ($OldUserPath -split ';') | Where-Object { $_ }
if ($PathEntries -notcontains $BinDir) {
    [Environment]::SetEnvironmentVariable('Path', (($PathEntries + $BinDir) -join ';'), 'User')
}
if (($env:Path -split ';') -notcontains $BinDir) { $env:Path = "$BinDir;$env:Path" }

$initArgs = @('init')
if ($ClaudeRoot) { $initArgs += @('--claude-root', $ClaudeRoot) }
if ($CodexRoot) { $initArgs += @('--codex-root', $CodexRoot) }
if (-not $Safe) { $initArgs += '--yolo' }
& $PythonExe @PythonPrefix $Installed @initArgs
if ($LASTEXITCODE -ne 0) { throw 'Configuration initialization failed.' }
$mode = if ($Safe) { 'safe' } else { 'yolo' }
& $PythonExe @PythonPrefix $Installed mode $mode
if ($LASTEXITCODE -ne 0) { throw 'Could not configure mode.' }

foreach ($provider in @('claude','codex')) {
    if (-not (Get-Command $provider -ErrorAction SilentlyContinue)) {
        Write-Warning "$provider CLI is missing. Install the official CLI (instructions in README)."
    }
}
if ($LoginAll) {
    & $PythonExe @PythonPrefix $Installed login-all
    if ($LASTEXITCODE -ne 0) { throw 'One or more logins failed; retry aifull login <provider> <slot>.' }
}
Write-Host "Installed: aifull, claudefull, codexfull" -ForegroundColor Green
Write-Host "New PowerShell: aifull doctor; aifull status; claudefull; codexfull"
Write-Warning 'YOLO bypasses approval and sandbox protection; restrict use to trusted local workspaces.'
