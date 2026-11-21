<#
.SYNOPSIS
    Runs the test suite and the probe elevated in Windows Sandbox and prints the result.

.DESCRIPTION
    Tests that start a trace session need elevation. Running them on a working
    machine leaves admin-owned files behind, and later code will change registry
    and service state. This runs them in a disposable sandbox instead.

    The sandbox gets three mapped folders and no network:
      - this repository, read-only
      - a Python installation from the host, read-only (nothing is downloaded)
      - tools\sandbox\results, writable: the logs and summary.json

    Only one sandbox can run at a time. This refuses to start while one is open
    and waits for a previous one that is still shutting down.

.PARAMETER PythonHome
    Folder of a Python 3.11+ installation that has pytest installed. Default: the
    base installation of the python on PATH. A virtual environment does not work,
    because it points back at an interpreter that is not mapped.

.PARAMETER TimeoutMinutes
    How long to wait for the run once the sandbox has started.

.PARAMETER KeepOpen
    Leave the sandbox open afterwards to look around. Close it before the next run.

.PARAMETER NoWait
    Return as soon as the result is printed. By default the script waits until
    the sandbox's virtual machine is gone, which takes several minutes after its
    window closes; until then the repository folder stays locked.

.OUTPUTS
    Exit code 0 when the suite and the probe both succeeded, 1 when either
    failed, 2 when the harness did not start or did not finish in time.

.EXAMPLE
    .\tools\sandbox\Invoke-SandboxRun.ps1
#>
[CmdletBinding()]
param(
    [string]$PythonHome,
    [int]$TimeoutMinutes = 15,
    [switch]$KeepOpen,
    [switch]$NoWait
)

$ErrorActionPreference = 'Stop'

$sandboxExe = Join-Path $env:WINDIR 'System32\WindowsSandbox.exe'
if (-not (Test-Path -LiteralPath $sandboxExe)) {
    throw 'Windows Sandbox is not enabled. Enable the Containers-DisposableClientVM optional feature and restart.'
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$resultsDir = Join-Path $PSScriptRoot 'results'
New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null

if (-not $PythonHome) {
    $PythonHome = (& python -c 'import sys; print(sys.base_prefix)').Trim()
}
if (-not (Test-Path -LiteralPath (Join-Path $PythonHome 'python.exe'))) {
    throw "No python.exe in $PythonHome. Pass -PythonHome."
}
if (-not (Test-Path -LiteralPath (Join-Path $PythonHome 'Lib\site-packages\pytest'))) {
    throw "pytest is not installed in $PythonHome. Install it there or pass another -PythonHome."
}

$windowProcesses = @('WindowsSandboxRemoteSession', 'WindowsSandboxServer')
if (@(Get-Process -Name $windowProcesses -ErrorAction SilentlyContinue).Count -gt 0) {
    throw 'A Windows Sandbox is already running. Close it, then run this again.'
}
# A sandbox that is still shutting down has no window, only its memory process,
# and one started on top of it can boot without its mapped folders.
if (@(Get-Process -Name 'vmmemWindowsSandbox' -ErrorAction SilentlyContinue).Count -gt 0) {
    Write-Host 'Waiting for the previous sandbox to finish shutting down...'
    $deadline = (Get-Date).AddMinutes(10)
    while ((Get-Date) -lt $deadline -and
           @(Get-Process -Name 'vmmemWindowsSandbox' -ErrorAction SilentlyContinue).Count -gt 0) {
        Start-Sleep -Seconds 5
    }
    Start-Sleep -Seconds 30
}

function Format-Map {
    param([string]$HostFolder, [string]$SandboxFolder, [string]$ReadOnly)
    $escaped = [System.Security.SecurityElement]::Escape($HostFolder)
    "    <MappedFolder><HostFolder>$escaped</HostFolder><SandboxFolder>$SandboxFolder</SandboxFolder><ReadOnly>$ReadOnly</ReadOnly></MappedFolder>"
}

$wsb = @"
<Configuration>
  <MappedFolders>
$(Format-Map $repoRoot 'C:\writehawk-src' 'true')
$(Format-Map $PythonHome 'C:\writehawk-python' 'true')
$(Format-Map $resultsDir 'C:\writehawk-results' 'false')
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\writehawk-src\tools\sandbox\Start-SandboxRun.ps1</Command>
  </LogonCommand>
  <MemoryInMB>4096</MemoryInMB>
  <Networking>Disable</Networking>
</Configuration>
"@
$wsbPath = Join-Path $env:TEMP ('writehawk-{0}.wsb' -f [guid]::NewGuid().ToString('N'))
Set-Content -LiteralPath $wsbPath -Value $wsb -Encoding UTF8

$summaryPath = Join-Path $resultsDir 'summary.json'
$transcriptPath = Join-Path $resultsDir 'transcript.log'
Remove-Item -LiteralPath $summaryPath -Force -ErrorAction SilentlyContinue

function Test-WrittenSince {
    param([string]$Path, [datetime]$Since)
    (Test-Path -LiteralPath $Path) -and ((Get-Item -LiteralPath $Path).LastWriteTime -gt $Since)
}

try {
    $launch = Get-Date
    Write-Host "Starting Windows Sandbox for $repoRoot"
    Start-Process -FilePath $sandboxExe -ArgumentList ('"{0}"' -f $wsbPath)

    $startDeadline = (Get-Date).AddMinutes(6)
    while ((Get-Date) -lt $startDeadline -and
           -not (Test-WrittenSince -Path $transcriptPath -Since $launch)) {
        Start-Sleep -Seconds 5
    }
    if (-not (Test-WrittenSince -Path $transcriptPath -Since $launch)) {
        Write-Host 'The harness did not start inside the sandbox. Check the sandbox window.'
        exit 2
    }
    Write-Host 'Harness started.'

    $finishDeadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ((Get-Date) -lt $finishDeadline -and
           -not (Test-WrittenSince -Path $summaryPath -Since $launch)) {
        Start-Sleep -Seconds 5
    }
    if (-not (Test-WrittenSince -Path $summaryPath -Since $launch)) {
        Write-Host "No result after $TimeoutMinutes minutes. See $transcriptPath."
        exit 2
    }
    Start-Sleep -Seconds 2

    $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
    foreach ($log in 'pytest.log', 'probe.log', 'trace.log', 'context.log', 'install.log') {
        $path = Join-Path $resultsDir $log
        if (Test-WrittenSince -Path $path -Since $launch) {
            Write-Host "--- $log"
            Get-Content -LiteralPath $path | Select-Object -Last 32
        }
    }
    foreach ($failed in Get-ChildItem -LiteralPath $resultsDir -Filter 'repeat-*.log' -ErrorAction SilentlyContinue) {
        if (Test-WrittenSince -Path $failed.FullName -Since $launch) {
            Write-Host "--- $($failed.Name)"
            Get-Content -LiteralPath $failed.FullName | Select-Object -Last 32
        }
    }
    Write-Host '--- summary'
    Write-Host ("Live tests repeated {0} times, {1} failed" -f $summary.RepeatRuns, $summary.RepeatFailures)
    Write-Host ("Scheduled report written: {0}, task removed afterwards: {1}" -f $summary.WatchReport, $summary.WatchRemoved)
    Write-Host ("Windows build {0}, elevated: {1}, pytest exit {2}, probe exit {3}, trace exit {4}, context exit {5}, install exit {6}" -f
        $summary.Build, $summary.Elevated, $summary.PytestExit, $summary.ProbeExit, $summary.TraceExit, $summary.ContextExit, $summary.InstallExit)
    if ($summary.Error) {
        Write-Host "Harness error: $($summary.Error)"
        exit 2
    }
    if ($summary.PytestExit -eq 0 -and $summary.ProbeExit -eq 0 -and $summary.TraceExit -eq 0 -and $summary.ContextExit -eq 0 -and $summary.InstallExit -eq 0 -and $summary.RepeatFailures -eq 0 -and $summary.WatchReport -and $summary.WatchRemoved) { exit 0 } else { exit 1 }
}
finally {
    Remove-Item -LiteralPath $wsbPath -Force -ErrorAction SilentlyContinue
    if (-not $KeepOpen) {
        Get-Process -Name $windowProcesses -ErrorAction SilentlyContinue | Stop-Process -Force
        if (-not $NoWait) {
            # The virtual machine outlives its window by several minutes and keeps the
            # mapped folders locked until it is gone.
            Write-Host 'Waiting for the sandbox to shut down (this can take several minutes)...'
            $deadline = (Get-Date).AddMinutes(12)
            while ((Get-Date) -lt $deadline -and
                   @(Get-Process -Name 'vmmemWindowsSandbox' -ErrorAction SilentlyContinue).Count -gt 0) {
                Start-Sleep -Seconds 10
            }
            if (@(Get-Process -Name 'vmmemWindowsSandbox' -ErrorAction SilentlyContinue).Count -gt 0) {
                Write-Host 'The sandbox is still shutting down.'
            }
            else {
                Write-Host 'Sandbox gone.'
            }
        }
    }
}
