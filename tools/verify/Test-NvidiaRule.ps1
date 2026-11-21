<#
.SYNOPSIS
    Checks the NVIDIA rule against the real bug, on a machine that has it.

.DESCRIPTION
    For a machine with an affected NVIDIA driver whose workaround is already in
    place (DisableLoad = 1 under the display container's _nvtopps key). It
    switches the workaround off for a few minutes to see whether writehawk
    catches the real bug, then lets writehawk switch it back on and undo and
    redo that, and compares the registry key with a backup taken at the start.

    Whatever happens, the machine ends with the workaround in place: the final
    step restores the key from the backup if it differs, and restarts the
    service.

    While the workaround is off the bug may write to the drive. Reports put the
    worst case at about 30 GB an hour; the window here is a few minutes.

    Run it from an administrator terminal, in the repository folder. Results go
    to tools\verify\results. Use -DryRun first to see every step.
#>
param(
    [int]$Seconds = 60,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'

$service = 'NVDisplay.ContainerLocalSystem'
$keyPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$service\Parameters\LocalSystem\_nvtopps"
$keyReg = "HKLM\SYSTEM\CurrentControlSet\Services\$service\Parameters\LocalSystem\_nvtopps"
$rule = 'nvidia-nvtopps-log-rewrite'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$results = Join-Path $PSScriptRoot 'results'
$ledger = Join-Path $results 'ledger'
$log = Join-Path $results 'nvidia-check.log'
$backup = Join-Path $results 'nvtopps-before.reg'

function Say([string]$text) {
    $line = "[{0}] {1}" -f (Get-Date).ToString('HH:mm:ss'), $text
    Write-Host $line
    if (-not $DryRun) { Add-Content -LiteralPath $log -Value $line -Encoding UTF8 }
}

function Writehawk([string]$title, [string[]]$arguments) {
    Say "--- ${title}: writehawk $($arguments -join ' ')"
    if ($DryRun) { return 0 }
    $env:PYTHONPATH = Join-Path $repo 'src'
    # A line on standard error must not stop the script.
    $ErrorActionPreference = 'Continue'
    $output = & python -m writehawk @arguments 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $output | ForEach-Object { Say "    $_" }
    Say "    (exit $code)"
    return $code
}

function Get-DisableLoad {
    $item = Get-ItemProperty -LiteralPath $keyPath -Name DisableLoad -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }
    return $item.DisableLoad
}

function Restart-Container {
    Say "restart service $service"
    if (-not $DryRun) { Restart-Service -Name $service -Force; Start-Sleep -Seconds 5 }
}

# --- preconditions ---------------------------------------------------------------
$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $DryRun -and -not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Run this from a terminal opened with "Run as administrator".'
    exit 2
}
if (-not (Get-Service -Name $service -ErrorAction SilentlyContinue)) {
    Write-Host "Service $service not found: this machine has no NVIDIA display driver."
    exit 2
}
if (-not $DryRun -and -not (Test-Path -LiteralPath $keyPath)) {
    Write-Host "Key $keyReg not found. This script expects the workaround to be in place."
    exit 2
}
$before = if ($DryRun) { 1 } else { Get-DisableLoad }
if ($before -ne 1) {
    Write-Host "DisableLoad is '$before', not 1. This script expects the workaround to be in place."
    exit 2
}
if (-not $DryRun) {
    New-Item -ItemType Directory -Path $results -Force | Out-Null
    Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
}

$summary = [ordered]@{ Started = (Get-Date).ToString('o') }
try {
    Say "1. back up the key to $backup"
    if (-not $DryRun) {
        reg export $keyReg $backup /y | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'reg export failed' }
    }
    $summary.Baseline = Writehawk '2. baseline, workaround in place (expect MITIGATED)' @('scan', '--seconds', '20')

    Say '3. switch the workaround off: remove DisableLoad'
    if (-not $DryRun) { Remove-ItemProperty -LiteralPath $keyPath -Name DisableLoad }
    Restart-Container
    Say "   wait 60 s for the plugin to start writing"
    if (-not $DryRun) { Start-Sleep -Seconds 60 }
    $summary.Exposed = Writehawk "4. bug free to run (expect ACTIVE if this machine shows it)" @('scan', '--seconds', "$Seconds")
    $null = Writehawk '   raw trace of the same period' @('trace', '--seconds', '30', '--min-kb', '64', '--limit', '10')

    $null = Writehawk '5. what the fix would change (dry run)' @('fix', $rule, '--ledger-dir', $ledger)
    $summary.Fix = Writehawk '6. apply the workaround with writehawk, restarting the service' @('fix', $rule, '--apply', '--now', '--ledger-dir', $ledger)
    $summary.AfterFix = Writehawk "7. after the fix (expect MITIGATED, no writes)" @('scan', '--seconds', "$Seconds")
    $null = Writehawk '8. what writehawk changed' @('status', '--ledger-dir', $ledger)

    $summary.Rollback = Writehawk '9. undo it from the ledger' @('rollback', '--apply', '--ledger-dir', $ledger)
    if (-not $DryRun) { Say ("   DisableLoad after rollback: '{0}' (expect empty)" -f (Get-DisableLoad)) }
    $summary.Refix = Writehawk '10. apply it again' @('fix', $rule, '--apply', '--now', '--ledger-dir', $ledger)
}
catch {
    Say "ERROR: $($_.Exception.Message)"
    $summary.Error = $_.Exception.Message
}
finally {
    if (-not $DryRun) {
        $now = Join-Path $results 'nvtopps-after.reg'
        reg export $keyReg $now /y | Out-Null
        $same = (Test-Path $now) -and ((Get-FileHash $now).Hash -eq (Get-FileHash $backup).Hash)
        $summary.KeyIdenticalToBackup = $same
        if (-not $same -or (Get-DisableLoad) -ne 1) {
            Say 'key differs from the backup: restoring it'
            reg import $backup | Out-Null
            Restart-Container
            $summary.Restored = $true
        }
        $summary.FinalDisableLoad = Get-DisableLoad
        $summary.Finished = (Get-Date).ToString('o')
        $summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $results 'nvidia-check.json') -Encoding UTF8
        Say ("final DisableLoad: {0}; key identical to the backup: {1}" -f $summary.FinalDisableLoad, $same)
    }
    else {
        Say 'finally: compare the key with the backup, restore and restart the service if it differs'
    }
}
