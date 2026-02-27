# ============================================================
# Unitrader - One-Click Startup Script
# Double-click or run:  powershell -ExecutionPolicy Bypass -File start.ps1
# ============================================================

$ROOT    = $PSScriptRoot
$BACKEND = $ROOT
$FRONTEND= Join-Path $ROOT "frontend"
$VENV    = Join-Path $ROOT "venv\Scripts\python.exe"
$LOG_DIR = Join-Path $ROOT "logs"

# ── Colours ──────────────────────────────────────────────────
function Green($m) { Write-Host $m -ForegroundColor Green }
function Yellow($m){ Write-Host $m -ForegroundColor Yellow }
function Red($m)   { Write-Host $m -ForegroundColor Red }
function Cyan($m)  { Write-Host $m -ForegroundColor Cyan }

Clear-Host
Cyan "============================================================"
Cyan "   UNITRADER  -  Starting All Services"
Cyan "============================================================"

# ── Create log folder ─────────────────────────────────────────
if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR | Out-Null }

# ── Kill anything on ports 3000 / 8000 ───────────────────────
Yellow "`n[1/4] Clearing ports 3000 and 8000..."
foreach ($port in @(3000, 8000)) {
    $pids = (netstat -ano | Select-String ":$port " | Select-String "LISTENING") -replace '.*\s+(\d+)$','$1'
    foreach ($p in $pids) {
        $p = $p.Trim()
        if ($p -match '^\d+$') {
            try {
                $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
                if ($proc) {
                    # Try Stop-Process first
                    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Milliseconds 500
                    # If still alive, use wmic
                    if (Get-Process -Id $p -ErrorAction SilentlyContinue) {
                        wmic process where "ProcessId=$p" delete | Out-Null
                    }
                    Yellow "  Killed PID $p on port $port"
                }
            } catch {}
        }
    }
}
Start-Sleep -Seconds 2
Green "  Ports cleared."

# ── Verify Python venv ────────────────────────────────────────
Yellow "`n[2/4] Checking Python environment..."
if (-not (Test-Path $VENV)) {
    Yellow "  venv not found — creating it..."
    Set-Location $BACKEND
    python -m venv venv
    & "$ROOT\venv\Scripts\pip.exe" install -r requirements.txt -q
}
Green "  Python environment ready."

# ── Start Backend ─────────────────────────────────────────────
Yellow "`n[3/4] Starting Backend (FastAPI on port 8000)..."
$backendLog = Join-Path $LOG_DIR "backend.log"
$backendProc = Start-Process -FilePath $VENV `
    -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port 8000 --reload" `
    -WorkingDirectory $BACKEND `
    -RedirectStandardOutput $backendLog `
    -RedirectStandardError  (Join-Path $LOG_DIR "backend_err.log") `
    -PassThru -WindowStyle Hidden

# Wait for backend to respond
$backendReady = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $backendReady = $true; break }
    } catch {}
    Write-Host "  Waiting for backend... ($($i+1)s)" -NoNewline
    Write-Host "`r" -NoNewline
}

if ($backendReady) {
    Green "  Backend is UP → http://localhost:8000"
    Green "  API Docs      → http://localhost:8000/docs"
} else {
    Red "  Backend failed to start. Check logs\backend_err.log"
}

# ── Start Frontend ────────────────────────────────────────────
Yellow "`n[4/4] Starting Frontend (Next.js on port 3000)..."
$frontendLog = Join-Path $LOG_DIR "frontend.log"
$frontendProc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c npm run dev > `"$frontendLog`" 2>&1" `
    -WorkingDirectory $FRONTEND `
    -PassThru -WindowStyle Hidden

# Wait for frontend to respond
$frontendReady = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:3000/" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $frontendReady = $true; break }
    } catch {}
    Write-Host "  Waiting for frontend... ($($i+1)s)" -NoNewline
    Write-Host "`r" -NoNewline
}

if ($frontendReady) {
    Green "  Frontend is UP → http://localhost:3000"
} else {
    Red "  Frontend failed to start. Check logs\frontend.log"
}

# ── Save PIDs for watchdog ────────────────────────────────────
@{ backend = $backendProc.Id; frontend = $frontendProc.Id } | 
    ConvertTo-Json | Set-Content (Join-Path $LOG_DIR "pids.json")

# ── Summary ───────────────────────────────────────────────────
Cyan "`n============================================================"
Cyan "   UNITRADER IS RUNNING"
Cyan "============================================================"
Green "  Landing Page : http://localhost:3000"
Green "  App Dashboard: http://localhost:3000/app"
Green "  Login        : http://localhost:3000/login"
Green "  API Docs     : http://localhost:8000/docs"
Cyan "------------------------------------------------------------"
Yellow "  Logs saved to: $LOG_DIR"
Yellow "  Run watchdog.ps1 in another window to auto-restart"
Cyan "============================================================"

# Keep window open so user can see the status
Write-Host "`nPress any key to exit this launcher (services keep running)..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
