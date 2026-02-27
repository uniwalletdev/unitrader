# ============================================================
# Unitrader - Watchdog (Auto-Restart Monitor)
# Run in a separate window. Keeps backend + frontend alive.
# Usage:  powershell -ExecutionPolicy Bypass -File watchdog.ps1
# ============================================================

$ROOT     = $PSScriptRoot
$BACKEND  = $ROOT
$FRONTEND = Join-Path $ROOT "frontend"
$VENV     = Join-Path $ROOT "venv\Scripts\python.exe"
$LOG_DIR  = Join-Path $ROOT "logs"

$CHECK_INTERVAL = 15   # seconds between health checks
$MAX_RESTARTS   = 10   # max restarts before giving up

if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR | Out-Null }

function Timestamp { Get-Date -Format "yyyy-MM-dd HH:mm:ss" }
function Log($msg, $color="White") { Write-Host "[$(Timestamp)] $msg" -ForegroundColor $color }

function Is-PortListening($port) {
    $r = netstat -ano | Select-String ":$port " | Select-String "LISTENING"
    return ($null -ne $r)
}

function Is-BackendHealthy {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Is-FrontendHealthy {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:3000/" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Kill-Port($port) {
    $pids = (netstat -ano | Select-String ":$port " | Select-String "LISTENING") -replace '.*\s+(\d+)$','$1'
    foreach ($p in $pids) {
        $p = $p.Trim()
        if ($p -match '^\d+$') {
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 300
            if (Get-Process -Id $p -ErrorAction SilentlyContinue) {
                wmic process where "ProcessId=$p" delete | Out-Null
            }
        }
    }
}

function Start-Backend {
    Log "Starting backend..." Yellow
    Kill-Port 8000
    Start-Sleep -Seconds 1
    $proc = Start-Process -FilePath $VENV `
        -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port 8000 --reload" `
        -WorkingDirectory $BACKEND `
        -RedirectStandardOutput (Join-Path $LOG_DIR "backend.log") `
        -RedirectStandardError  (Join-Path $LOG_DIR "backend_err.log") `
        -PassThru -WindowStyle Hidden

    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Is-BackendHealthy) {
            Log "Backend is UP (PID $($proc.Id))" Green
            return $proc
        }
    }
    Log "Backend failed to start. Check logs/backend_err.log" Red
    return $null
}

function Start-Frontend {
    Log "Starting frontend..." Yellow
    Kill-Port 3000
    Start-Sleep -Seconds 1
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c npm run dev >> `"$(Join-Path $LOG_DIR 'frontend.log')`" 2>&1" `
        -WorkingDirectory $FRONTEND `
        -PassThru -WindowStyle Hidden

    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 1
        if (Is-FrontendHealthy) {
            Log "Frontend is UP (PID $($proc.Id))" Green
            return $proc
        }
    }
    Log "Frontend failed to start. Check logs/frontend.log" Red
    return $null
}

# ── Initial start ─────────────────────────────────────────────
Clear-Host
Log "============================================" Cyan
Log "  UNITRADER WATCHDOG - Auto-Restart Monitor" Cyan
Log "============================================" Cyan
Log "Checking interval: ${CHECK_INTERVAL}s | Max restarts: $MAX_RESTARTS" Yellow

$backendRestarts  = 0
$frontendRestarts = 0

# Start both if not already running
if (-not (Is-BackendHealthy))  { Start-Backend  | Out-Null }
if (-not (Is-FrontendHealthy)) { Start-Frontend | Out-Null }

Log "`nWatchdog active. Monitoring every ${CHECK_INTERVAL}s..." Cyan
Log "  http://localhost:3000  (Frontend)" Green
Log "  http://localhost:8000  (Backend)" Green
Log "  Press Ctrl+C to stop watchdog`n" Yellow

# ── Main monitoring loop ──────────────────────────────────────
while ($true) {
    Start-Sleep -Seconds $CHECK_INTERVAL

    # --- Backend check ---
    if (-not (Is-BackendHealthy)) {
        $backendRestarts++
        Log "Backend DOWN (restart #$backendRestarts)" Red
        if ($backendRestarts -le $MAX_RESTARTS) {
            Start-Backend | Out-Null
        } else {
            Log "Backend exceeded max restarts ($MAX_RESTARTS). Manual intervention needed." Red
        }
    } else {
        Log "Backend  OK | Frontend checking..." DarkGray
    }

    # --- Frontend check ---
    if (-not (Is-FrontendHealthy)) {
        $frontendRestarts++
        Log "Frontend DOWN (restart #$frontendRestarts)" Red
        if ($frontendRestarts -le $MAX_RESTARTS) {
            Start-Frontend | Out-Null
        } else {
            Log "Frontend exceeded max restarts ($MAX_RESTARTS). Manual intervention needed." Red
        }
    } else {
        Log "Frontend OK" DarkGray
    }

    # Save status
    @{
        timestamp         = (Timestamp)
        backend_healthy   = (Is-BackendHealthy)
        frontend_healthy  = (Is-FrontendHealthy)
        backend_restarts  = $backendRestarts
        frontend_restarts = $frontendRestarts
    } | ConvertTo-Json | Set-Content (Join-Path $LOG_DIR "watchdog_status.json")
}
