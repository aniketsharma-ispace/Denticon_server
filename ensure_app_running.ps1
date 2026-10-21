# ensure_app_running.ps1
# Ensures the Denticon FastAPI app is up and healthy on :8000.
# Safe to run repeatedly: it starts the app only if it is missing or unhealthy.
# Used by the "DenticonServer" scheduled task (at boot + periodic watchdog).

$ErrorActionPreference = 'SilentlyContinue'

$proj = 'C:\Users\aniket.sharma\Documents\Denticon_server'
$py   = Join-Path $proj 'venv\Scripts\python.exe'
$port = 8000
$log  = Join-Path $proj 'app_watchdog.log'

function Write-Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

# 1. Is something listening on the port?
$listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if ($listening) {
    # 2. Self-check: is it actually healthy (responds to /api/health)?
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { return }   # healthy — nothing to do
    } catch { }

    # Port held but not responding -> stale/hung process. Replace it.
    $stalePid = $listening.OwningProcess | Select-Object -First 1
    Write-Log "Port $port held by PID $stalePid but health check failed; restarting."
    Stop-Process -Id $stalePid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
} else {
    Write-Log "App not running on port $port; starting it."
}

# 3. Start the app (hidden window, detached).
Start-Process -FilePath $py -ArgumentList 'main.py' -WorkingDirectory $proj -WindowStyle Hidden

# 4. Confirm it came up.
Start-Sleep -Seconds 4
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Log "App is listening on port $port."
} else {
    Write-Log "WARNING: app did not come up on port $port."
}
