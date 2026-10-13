# Local single-user run for testing (Windows). NOT for production - see docs/instalacja.md.
#   powershell -ExecutionPolicy Bypass -File scripts\dev_server.ps1
# Data (SQLite, uploaded PDFs, secrets) is kept in .\data (git-ignored).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$data = Join-Path $root "data"
New-Item -ItemType Directory -Force $data | Out-Null
$python = Join-Path $root ".venv\Scripts\python.exe"

# Secrets generated once and reused, so stored cases stay readable between runs.
$secrets = Join-Path $data "dev.env"
if (-not (Test-Path $secrets)) {
    & $python -c "import secrets; from cryptography.fernet import Fernet; print('CLAIMS_SECRET_KEY=' + secrets.token_urlsafe(48)); print('CLAIMS_MAPPING_KEY=' + Fernet.generate_key().decode())" |
        Set-Content -Path $secrets -Encoding ascii
}
Get-Content $secrets | ForEach-Object {
    $name, $value = $_ -split "=", 2
    if ($name) { Set-Item -Path "env:$name" -Value $value }
}

$env:CLAIMS_DATA_DIR = $data
$env:CLAIMS_DATABASE_URL = "sqlite:///" + ($data -replace "\\", "/") + "/claims.db"
$env:CLAIMS_SECURE_COOKIES = "false"
$env:CLAIMS_REQUIRE_ANON_APPROVAL = "true"

# Claude API key and Tesseract from the user's Windows settings.
$env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
if (-not $env:ANTHROPIC_API_KEY) { Write-Warning "ANTHROPIC_API_KEY is not set - analysis will fail." }
$tessdata = [Environment]::GetEnvironmentVariable("TESSDATA_PREFIX", "User")
if ($tessdata) { $env:TESSDATA_PREFIX = $tessdata }
if (Test-Path "C:\Program Files\Tesseract-OCR") { $env:Path += ";C:\Program Files\Tesseract-OCR" }

if ($args[0] -eq "create-user") {
    & $python scripts\dev_create_user.py @($args | Select-Object -Skip 1)
    exit $LASTEXITCODE
}

Write-Host "Aplikacja: http://localhost:8000  (Ctrl+C zatrzymuje)" -ForegroundColor Green
& $python -m uvicorn app.main:build --factory --host 127.0.0.1 --port 8000
