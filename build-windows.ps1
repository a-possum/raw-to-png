param([ValidateSet('test', 'release')][string]$Channel = 'test')

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Command failed: $LASTEXITCODE" } }
py -3.12 -m venv .venv
Check-Exit
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $Python -m pip install -r requirements-dev.txt
Check-Exit
& $Python -m pytest -q
Check-Exit
$BuildProfileDirectory = Join-Path $PSScriptRoot 'build-config'
New-Item -ItemType Directory -Force $BuildProfileDirectory | Out-Null
$BuildProfilePath = Join-Path $BuildProfileDirectory 'build-profile.json'
@{ channel = $Channel } | ConvertTo-Json | Set-Content -Encoding UTF8 $BuildProfilePath
& $Python -m PyInstaller --noconfirm --clean --noupx --onedir --windowed --name ARW-to-PNG --icon raw_to_png/assets/app.ico --collect-all rawpy --copy-metadata PySide6 --copy-metadata psutil --copy-metadata pypng --add-data "$BuildProfilePath;raw_to_png" --add-data 'raw_to_png/assets/app.ico;raw_to_png/assets' main.py
Check-Exit
Write-Host 'Ready: dist\ARW-to-PNG\ARW-to-PNG.exe. Distribute the entire ARW-to-PNG folder.'
Write-Host "Build channel: $Channel"
