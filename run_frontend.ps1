$ErrorActionPreference = "Stop"

$existingFrontend = $false
$frontendCssHealthy = $false
try {
    $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:3000/login" -TimeoutSec 2
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        $existingFrontend = $true
        $cssMatch = [regex]::Match($response.Content, 'href="([^"]+\.css[^"]*)"')
        if ($cssMatch.Success) {
            $cssUrl = "http://127.0.0.1:3000" + $cssMatch.Groups[1].Value
            try {
                $cssResponse = Invoke-WebRequest -UseBasicParsing $cssUrl -TimeoutSec 2
                $frontendCssHealthy = $cssResponse.StatusCode -eq 200 -and $cssResponse.Content.Length -gt 1000
            }
            catch {
                $frontendCssHealthy = $false
            }
        }
    }
}
catch {
    $existingFrontend = $false
}

if ($existingFrontend -and $frontendCssHealthy) {
    Write-Host "Frontend deja lance : http://127.0.0.1:3000/login" -ForegroundColor Green
    exit 0
}

if ($existingFrontend -and -not $frontendCssHealthy) {
    Write-Host "Frontend detecte, mais CSS Next.js indisponible. Redemarrage propre..." -ForegroundColor Yellow
    $stalePortLine = netstat -ano | Select-String "127\.0\.0\.1:3000\s+.*LISTENING" | Select-Object -First 1
    if ($stalePortLine) {
        $stalePidText = (($stalePortLine -split "\s+") | Select-Object -Last 1)
        try {
            Stop-Process -Id ([int]$stalePidText) -Force
            Start-Sleep -Seconds 2
        }
        catch {
            Write-Host "Impossible d'arreter le PID $stalePidText. Arrete-le manuellement puis relance ce script." -ForegroundColor Red
            exit 1
        }
    }
}

$portLine = netstat -ano | Select-String "127\.0\.0\.1:3000\s+.*LISTENING"
if ($portLine) {
    $pidText = (($portLine -split "\s+") | Select-Object -Last 1)
    Write-Host "Le port 3000 est deja utilise par le PID $pidText." -ForegroundColor Yellow
    Write-Host "Si ce n'est pas le frontend DocIA, arrete-le avec : taskkill /PID $pidText /F" -ForegroundColor Yellow
    exit 1
}

Write-Host "Lancement frontend Next.js..." -ForegroundColor Green
Set-Location "$PSScriptRoot\frontend"
if (-not (Test-Path ".\node_modules")) {
    Write-Host "Installation des dependances frontend..." -ForegroundColor Yellow
    if (Get-Command corepack -ErrorAction SilentlyContinue) {
        corepack pnpm install
    }
    else {
        npm install
    }
}

if (Test-Path ".\.next") {
    Write-Host "Nettoyage du cache Next.js..." -ForegroundColor Yellow
    Remove-Item -LiteralPath ".\.next" -Recurse -Force
}

if (Test-Path ".\node_modules\.bin\next.CMD") {
    .\node_modules\.bin\next.CMD dev --hostname 127.0.0.1 --port 3000
}
elseif (Get-Command corepack -ErrorAction SilentlyContinue) {
    corepack pnpm dev --hostname 127.0.0.1 --port 3000
}
else {
    npm run dev -- --hostname 127.0.0.1 --port 3000
}
