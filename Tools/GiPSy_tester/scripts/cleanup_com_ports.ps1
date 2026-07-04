<#
.SYNOPSIS
    List (and optionally remove) stale ArduPilot USB serial device
    entries from Windows so they stop accumulating a new COM port
    number every time a GiPSy/GiPSy-mini/PatrionicPH7X board is
    plugged in or switches between bootloader and app mode.

.DESCRIPTION
    ArduPilot ChibiOS boards report a persistent USB serial number
    derived from the CPU UID, but the bootloader and application
    firmware enumerate as separate device instances even for the
    same physical board (same VID:PID 1209:5741, different USB
    configuration/state). Windows keeps a device node - and COM
    port assignment - per instance ID it has ever seen, even after
    the device is unplugged. Over many flash/reboot cycles this
    accumulates a large number of dead COM ports in Device Manager.

    This script only targets devices matching ArduPilot's VID
    (1209). It NEVER touches a device that is currently connected -
    only entries for hardware that is not present right now.

.PARAMETER Remove
    Actually remove the stale entries. Without this switch the
    script only lists what it would remove (dry run).

.NOTES
    Removing device entries requires an elevated (Administrator)
    PowerShell session and the pnputil driver-management tool.
    This is a Windows device-tree change - review the listed
    devices before re-running with -Remove.
#>
[CmdletBinding()]
param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

Write-Host "Scanning for ArduPilot USB serial devices (VID 1209)..." -ForegroundColor Cyan

$devices = Get-PnpDevice -Class Ports -PresentOnly:$false |
    Where-Object { $_.InstanceId -match "VID_1209" }

if (-not $devices) {
    Write-Host "No ArduPilot (VID_1209) serial devices found in the device tree." -ForegroundColor Yellow
    return
}

$present = $devices | Where-Object { $_.Status -eq "OK" }
$stale = $devices | Where-Object { $_.Status -ne "OK" }

Write-Host ""
Write-Host "Currently connected (will NOT be touched):" -ForegroundColor Green
$present | Select-Object FriendlyName, InstanceId, Status | Format-Table -AutoSize

Write-Host ""
Write-Host "Stale / not present (candidates for removal):" -ForegroundColor Yellow
$stale | Select-Object FriendlyName, InstanceId, Status | Format-Table -AutoSize

if (-not $stale) {
    Write-Host "Nothing stale to clean up." -ForegroundColor Green
    return
}

if (-not $Remove) {
    Write-Host ""
    Write-Host "Dry run only. Re-run with -Remove to actually remove the $($stale.Count) stale entrie(s) listed above." -ForegroundColor Cyan
    return
}

Write-Host ""
Write-Host "Removing $($stale.Count) stale device entrie(s)..." -ForegroundColor Cyan
foreach ($dev in $stale) {
    Write-Host "  Removing $($dev.InstanceId)"
    & pnputil /remove-device "$($dev.InstanceId)" | Out-Null
}
Write-Host "Done." -ForegroundColor Green
