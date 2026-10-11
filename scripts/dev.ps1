<#
.SYNOPSIS
  Common PrescripTrace tasks for Windows PowerShell.
.EXAMPLE
  .\scripts\dev.ps1 up
  .\scripts\dev.ps1 test
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "dev", "down", "logs", "migrate", "test", "test-backend", "test-frontend", "lint", "fmt", "shell-db", "help")]
    [string]$Task = "help"
)

# Not "Stop": Windows PowerShell 5.1 turns docker/npm progress on stderr into terminating
# errors when output is redirected. Failures are detected via $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked([scriptblock]$Block) {
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}

function Get-AppUrl {
    $port = "5173"
    $line = Get-Content ".env" -ErrorAction SilentlyContinue | Where-Object { $_ -match "^FRONTEND_PORT=(\d+)" } | Select-Object -First 1
    if ($line -match "^FRONTEND_PORT=(\d+)") { $port = $Matches[1] }
    return "http://localhost:$port"
}

# Wait until the website answers (the first start builds the app, ~1 min), then open it.
function Wait-ForApp {
    $url = Get-AppUrl
    Write-Host "Starting PrescripTrace at $url ..." -NoNewline
    $health = $null
    for ($i = 0; $i -lt 90; $i++) {
        try {
            $health = Invoke-RestMethod -Uri "$url/api/v1/health" -TimeoutSec 5 -ErrorAction Stop
            if ($health.search_ready -or $health.datasets_loaded -eq 0) { break }
        } catch { }
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
    }
    Write-Host ""
    if ($null -eq $health) {
        Write-Host "The app did not answer yet. See what is happening with: .\scripts\dev.ps1 logs" -ForegroundColor Yellow
        return
    }
    if ($health.datasets_loaded -eq 0) {
        Write-Host "The app is running, but no drug data is loaded yet. Load it once (1-2 hours):" -ForegroundColor Yellow
        Write-Host "  docker compose run --rm backend python -m app.ingest all"
        Write-Host "  docker compose restart backend"
    }
    Write-Host "PrescripTrace is ready: $url   (API docs: $url/api/docs)" -ForegroundColor Green
    Start-Process $url
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example (edit the password before sharing this machine)."
}

switch ($Task) {
    "up"            { Invoke-Checked { docker compose up -d --build }
                      Wait-ForApp }
    "dev"           { # Hot-reloading frontend on this machine (needs `npm ci` in frontend once);
                      # database and API still run in Docker.
                      Invoke-Checked { docker compose up -d --build db backend }
                      Push-Location frontend; try { npm run dev -- --open } finally { Pop-Location } }
    "down"          { Invoke-Checked { docker compose down } }
    "logs"          { docker compose logs -f backend frontend }
    "migrate"       { Invoke-Checked { docker compose run --rm backend alembic upgrade head } }
    "test-backend"  { Invoke-Checked { docker compose run --rm backend pytest -q } }
    "test-frontend" { Push-Location frontend; try { Invoke-Checked { npm test } } finally { Pop-Location } }
    "test"          { & $PSCommandPath test-backend; & $PSCommandPath test-frontend }
    "lint"          { Invoke-Checked { docker compose run --rm --no-deps backend sh -c "ruff check . && ruff format --check . && mypy app" }
                      Push-Location frontend; try { Invoke-Checked { npm run lint }; Invoke-Checked { npm run typecheck } } finally { Pop-Location } }
    "fmt"           { Invoke-Checked { docker compose run --rm --no-deps backend sh -c "ruff check --fix . && ruff format ." } }
    "shell-db"      { docker compose exec db psql -U prescriptrace -d prescriptrace }
    default         { Get-Help $PSCommandPath -Detailed }
}
