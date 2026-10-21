# register_autostart_task.ps1
# Run ONCE from an ELEVATED (Administrator) PowerShell.
# Registers a scheduled task that keeps the Denticon app running:
#   - starts it at system boot (as SYSTEM, before any login)
#   - re-checks every 5 minutes and restarts it if it died (watchdog)
# The actual start/health logic lives in ensure_app_running.ps1.

$ErrorActionPreference = 'Stop'

$taskName = 'DenticonServer'
$script   = 'C:\Users\aniket.sharma\Documents\Denticon_server\ensure_app_running.ps1'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""

# Trigger: at boot, then repeat every 5 minutes as a watchdog.
$trigger = New-ScheduledTaskTrigger -AtStartup
$rep = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) `
            -RepetitionDuration (New-TimeSpan -Days 3650)).Repetition
$trigger.Repetition = $rep

# Run as SYSTEM with highest privileges so it works with no one logged in.
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

# Replace any previous copy, then register.
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'Starts the Denticon FastAPI app at boot and keeps it alive (5-min health watchdog).'

Write-Host "Registered scheduled task '$taskName'." -ForegroundColor Green
Write-Host "Kicking it off now to verify..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 6
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "OK - app is listening on port 8000." -ForegroundColor Green
} else {
    Write-Host "App not up yet - check app_watchdog.log in the project folder." -ForegroundColor Yellow
}
