$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$existingApi = $false
try {
    $health = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/health" -TimeoutSec 2
    if ($health.StatusCode -ge 200 -and $health.StatusCode -lt 300) {
        $existingApi = $true
    }
}
catch {
    $existingApi = $false
}

if ($existingApi) {
    Write-Host "Backend deja lance : http://127.0.0.1:8000" -ForegroundColor Green
    Write-Host "Health check : http://127.0.0.1:8000/api/health" -ForegroundColor Cyan
    exit 0
}

$portLine = netstat -ano | Select-String "127\.0\.0\.1:8000\s+.*LISTENING"
if ($portLine) {
    $pidText = (($portLine -split "\s+") | Select-Object -Last 1)
    Write-Host "Le port 8000 est deja utilise par le PID $pidText." -ForegroundColor Yellow
    Write-Host "Si ce n'est pas le backend DocuAI, arrete-le avec : taskkill /PID $pidText /F" -ForegroundColor Yellow
    exit 1
}

Write-Host "Lancement backend FastAPI..." -ForegroundColor Green
$localPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$serverScript = Join-Path $PSScriptRoot "backend\run_server.py"

if (Test-Path $localPython) {
    & $localPython $serverScript
}
elseif ($pythonCommand -and $pythonCommand.Source -notlike "*\WindowsApps\*") {
    python $serverScript
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py $serverScript
}
else {
    throw "Python introuvable. Installe Python ou ajoute-le au PATH."
}
