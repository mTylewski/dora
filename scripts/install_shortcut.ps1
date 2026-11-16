# Creates the "DORA" icon on the desktop (once). The icon runs scripts\start_dora.ps1.
#   powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$icon = Join-Path $root "data\dora.ico"

& $python (Join-Path $root "scripts\make_icon.py") $icon | Out-Null

$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "DORA.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = "-NoLogo -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\scripts\start_dora.ps1`""
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "DORA - analiza roszczeń: uruchamia serwer i otwiera aplikację oraz okno ewaluacji"
$shortcut.WindowStyle = 7  # minimized
$shortcut.Save()
Write-Host "Utworzono skrót: $link"
