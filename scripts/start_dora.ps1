# DORA launcher for the desktop icon (Windows, local single-user run).
# Starts the server if it is not running yet, waits until it answers, then opens two browser
# windows: the application and the evaluation window. Closing the "DORA - serwer" window stops it.
#   powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File scripts\start_dora.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$base = "http://localhost:8000"
$appUrl = "$base/"
$evalUrl = "$base/admin/usage"
# Health checks go to 127.0.0.1 directly: on Windows "localhost" tries IPv6 (::1) first, and a
# refused IPv6 connection is retried for ~2 s before falling back, which exceeds the check timeout.
$probe = "http://127.0.0.1:8000"
$timeoutSeconds = 120

Add-Type -AssemblyName System.Windows.Forms

function Test-Dora {
    try {
        $r = Invoke-WebRequest "$probe/healthz" -UseBasicParsing -TimeoutSec 3
        return $r.Content.Trim() -eq "ok"
    } catch { return $false }
}

function Show-Error([string]$text) {
    [System.Windows.Forms.MessageBox]::Show($text, "DORA", "OK", "Error") | Out-Null
}

function Test-PortBusy {
    return [bool](Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
}

if (-not (Test-Dora)) {
    if (Test-PortBusy) {
        Show-Error "Port 8000 jest zajęty przez inny program, więc DORA nie może wystartować.`nZamknij ten program albo uruchom komputer ponownie."
        exit 1
    }
    $server = Join-Path $root "scripts\dev_server.ps1"
    # -NoExit keeps the window open after an error so the message can be read.
    Start-Process powershell.exe -WorkingDirectory $root -WindowStyle Minimized -ArgumentList @(
        "-NoLogo", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$server`""
    ) | Out-Null
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while (-not (Test-Dora)) {
        if ((Get-Date) -gt $deadline) {
            Show-Error "Serwer DORA nie odpowiada po $timeoutSeconds s.`nOtwórz zminimalizowane okno 'DORA - serwer' na pasku zadań i sprawdź komunikat błędu."
            exit 1
        }
        Start-Sleep -Milliseconds 700
    }
}

# Two separate windows: the evaluation window first, then the application on top of it.
$browsers = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if ($browsers) {
    $browser = $browsers[0]
    Start-Process $browser -ArgumentList @("--new-window", $evalUrl) | Out-Null
    Start-Sleep -Milliseconds 800
    Start-Process $browser -ArgumentList @("--new-window", $appUrl) | Out-Null
} else {
    Start-Process $evalUrl | Out-Null   # default browser, as tabs
    Start-Process $appUrl | Out-Null
}
