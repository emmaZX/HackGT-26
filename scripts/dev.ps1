$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
if (-not (Test-Path "frontend\.env.local")) { Copy-Item "frontend\.env.example" "frontend\.env.local" }

$venvPython = Join-Path $root "backend\.venv\Scripts\python.exe"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; & '$venvPython' -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"
