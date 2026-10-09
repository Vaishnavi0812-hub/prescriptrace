<#
.SYNOPSIS
  Common PrescripTrace tasks for Windows PowerShell.
.EXAMPLE
  .\scripts\dev.ps1 up
  .\scripts\dev.ps1 test
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "down", "logs", "migrate", "test", "test-backend", "test-frontend", "lint", "fmt", "shell-db", "help")]
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

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example (edit the password before sharing this machine)."
}

switch ($Task) {
    "up"            { Invoke-Checked { docker compose up -d --build }
                      Write-Host "Frontend: http://localhost:5173   API docs: http://localhost:8000/api/docs" }
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
