<#
.SYNOPSIS
    Runs the test suite and the probe elevated, inside Windows Sandbox.

.DESCRIPTION
    Started by the logon command that Invoke-SandboxRun.ps1 writes. The
    repository and a Python installation are mapped read-only; the results
    folder is the only writable map and the only thing that survives when the
    sandbox closes.

    summary.json is written last. The host waits for it.
#>
$ErrorActionPreference = 'Stop'

$source = 'C:\writehawk-src'
$python = 'C:\writehawk-python\python.exe'
$results = 'C:\writehawk-results'
$work = 'C:\writehawk-run'
$scratch = 'C:\writehawk-tmp'

if (-not (Test-Path -LiteralPath $results)) { exit 2 }
try { Start-Transcript -Path (Join-Path $results 'transcript.log') -Force | Out-Null } catch { }

$summary = [ordered]@{
    Started    = (Get-Date).ToString('o')
    Build      = [Environment]::OSVersion.Version.ToString()
    Elevated   = $false
    PytestExit = $null
    ProbeExit  = $null
    TraceExit  = $null
    RepeatRuns = 0
    RepeatFailures = 0
    ContextExit = $null
    InstallExit = $null
    WatchReport = $false
    WatchRemoved = $false
    Error      = $null
}

function Invoke-Logged {
    param([string]$Log, [string[]]$Arguments)
    # cmd does the redirection so stderr lines are not wrapped as PowerShell errors.
    $line = '"{0}" {1} > "{2}" 2>&1' -f $python, ($Arguments -join ' '), $Log
    cmd /c $line
    return $LASTEXITCODE
}

try {
    foreach ($path in $source, $python) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Not mapped: $path" }
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $summary.Elevated = ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)

    # Work on a copy: the map is read-only, and the host tree must stay untouched.
    robocopy $source $work /E /XD .* __pycache__ build dist results /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with $LASTEXITCODE" }
    New-Item -ItemType Directory -Path $scratch -Force | Out-Null

    Set-Location $work
    $env:PYTHONPATH = Join-Path $work 'src'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    # Lets tests that change the system know they are in a disposable machine.
    $env:WRITEHAWK_SANDBOX = '1'

    $summary.PytestExit = Invoke-Logged -Log (Join-Path $results 'pytest.log') -Arguments @(
        '-m', 'pytest', '-rs', '-p', 'no:cacheprovider', '-o', 'faulthandler_timeout=60', '--basetemp', "$scratch\pt")
    # The live and sandbox-only tests depend on timing between processes. One pass proves
    # little, so they run again several times; a failing pass keeps its log.
    foreach ($pass in 1..10) {
        $log = Join-Path $results "repeat-$pass.log"
        $code = Invoke-Logged -Log $log -Arguments @(
            '-m', 'pytest', '-q', '-k', '"test_sandbox or test_live"', '-p', 'no:cacheprovider',
            '-o', 'faulthandler_timeout=60',
            '--basetemp', "$scratch\rp$pass")
        $summary.RepeatRuns++
        if ($code -eq 0) { Remove-Item -LiteralPath $log -Force } else { $summary.RepeatFailures++ }
    }
    $summary.ProbeExit = Invoke-Logged -Log (Join-Path $results 'probe.log') -Arguments @(
        '-m', 'writehawk', 'probe', '--dir', $scratch)
    # A look at the sandbox's own background writers, services included.
    $summary.TraceExit = Invoke-Logged -Log (Join-Path $results 'trace.log') -Arguments @(
        '-m', 'writehawk', 'trace', '--seconds', '20', '--min-kb', '16')
    $summary.ContextExit = Invoke-Logged -Log (Join-Path $results 'context.log') -Arguments @(
        '-m', 'writehawk', 'context')

    # Build the package, install it into a new environment and use the installed
    # command, the way a user would. No network: nothing is downloaded.
    $installLog = Join-Path $results 'install.log'
    $env:PYTHONPATH = ''
    $venv = 'C:\writehawk-venv'
    $steps = @(
        "`"$python`" -m pip wheel . --no-deps --no-index --no-build-isolation -w `"$scratch\dist`"",
        "`"$python`" -m venv `"$venv`"",
        "for %w in (`"$scratch\dist\*.whl`") do `"$venv\Scripts\python.exe`" -m pip install --no-index --no-deps `"%w`"",
        "`"$venv\Scripts\writehawk.exe`" --version",
        "`"$venv\Scripts\writehawk.exe`" scan --seconds 5",
        "`"$venv\Scripts\writehawk.exe`" status",
        "`"$venv\Scripts\writehawk.exe`" selftest"
    )
    Set-Content -LiteralPath $installLog -Value '' -Encoding ASCII
    $summary.InstallExit = 0
    foreach ($step in $steps) {
        cmd /c "$step >> `"$installLog`" 2>&1"
        if ($LASTEXITCODE -ne 0 -and $summary.InstallExit -eq 0) { $summary.InstallExit = $LASTEXITCODE }
    }

    # The scheduled report, through the installed command: register it, run it
    # once, wait for its file, remove it, and check that the task is gone.
    $watchOut = Join-Path $scratch 'watch-report.json'
    cmd /c "`"$venv\Scripts\writehawk.exe`" watch install --out `"$watchOut`" >> `"$installLog`" 2>&1"
    cmd /c "schtasks /run /tn `"writehawk report`" >> `"$installLog`" 2>&1"
    $deadline = (Get-Date).AddSeconds(180)
    while (-not (Test-Path -LiteralPath $watchOut) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    $summary.WatchReport = Test-Path -LiteralPath $watchOut
    if ($summary.WatchReport) { Copy-Item -LiteralPath $watchOut -Destination (Join-Path $results 'watch-report.json') -Force }
    cmd /c "`"$venv\Scripts\writehawk.exe`" watch remove >> `"$installLog`" 2>&1"
    cmd /c "schtasks /query /tn `"writehawk report`" > nul 2>&1"
    $summary.WatchRemoved = ($LASTEXITCODE -ne 0)
}
catch {
    $summary.Error = $_.Exception.Message
}
finally {
    $summary.Finished = (Get-Date).ToString('o')
    $summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $results 'summary.json') -Encoding UTF8
    try { Stop-Transcript | Out-Null } catch { }
}
