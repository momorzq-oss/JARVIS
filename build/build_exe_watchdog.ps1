param(
    [int]$PollSeconds = 30,
    [int]$StaleMinutes = 5,
    [int]$TimeoutMinutes = 30,
    [string]$CandidateName = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logPath = Join-Path $PSScriptRoot 'pyinstaller-onedir.log'
$statusPath = Join-Path $PSScriptRoot 'build-status.json'
if ($CandidateName) {
    if ($CandidateName -notmatch '^JARVIS-FULL-COMMAND-RECOVERY-\d{8}-\d{6}$') {
        throw "Invalid candidate name: $CandidateName"
    }
    $distRoot = Join-Path $projectRoot ("release\candidates\$CandidateName")
    $workRoot = Join-Path $PSScriptRoot $CandidateName
    $exePath = Join-Path $distRoot 'JARVIS\JARVIS.exe'
} else {
    $distRoot = Join-Path $projectRoot 'dist'
    $workRoot = $null
    $exePath = Join-Path $distRoot 'JARVIS\JARVIS.exe'
}
$python = (& py -3.12 -c "import sys; print(sys.executable)").Trim()
$logicalProcessors = [Environment]::ProcessorCount
$started = Get-Date
$stopwatch = [Diagnostics.Stopwatch]::StartNew()

function Save-Status {
    param(
        [string]$Status,
        [string]$Reason,
        [Nullable[int]]$ExitCode = $null
    )
    $payload = [ordered]@{
        status = $Status
        reason = $Reason
        exit_code = $ExitCode
        started = $started.ToString('o')
        finished = (Get-Date).ToString('o')
        duration_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 2)
        executable = $exePath
    }
    if (Test-Path -LiteralPath $exePath) {
        $item = Get-Item -LiteralPath $exePath
        $payload.exe_size = $item.Length
        $payload.exe_modified = $item.LastWriteTime.ToString('o')
        $payload.sha256 = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash
    }
    $payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statusPath -Encoding UTF8
}

function Get-TreeProcessIds {
    param([int]$RootId)
    $ids = [Collections.Generic.HashSet[int]]::new()
    [void]$ids.Add($RootId)
    try {
        $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    } catch {
        # WMI can transiently return 0x80041033 (provider shutting down) while
        # PyInstaller loads many native modules.  Monitoring the verified root
        # worker is safer than aborting and orphaning its active child build.
        return @($ids)
    }
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($process in $all) {
            if ($ids.Contains([int]$process.ParentProcessId) -and -not $ids.Contains([int]$process.ProcessId)) {
                [void]$ids.Add([int]$process.ProcessId)
                $changed = $true
            }
        }
    }
    return @($ids)
}

function Get-TreeCpuSeconds {
    param([int]$RootId)
    $total = 0.0
    foreach ($id in Get-TreeProcessIds -RootId $RootId) {
        $process = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($process) {
            $total += [double]$process.CPU
        }
    }
    return $total
}

function Stop-ProcessTree {
    param([int]$RootId)
    & taskkill.exe /PID $RootId /T /F 2>&1 | Out-Null
}

foreach ($path in @($logPath, $statusPath)) {
    if (Test-Path -LiteralPath $path) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $archive = "$path.previous-$stamp"
        Move-Item -LiteralPath $path -Destination $archive -Force
    }
}

$candidateArguments = if ($CandidateName) {
    "--distpath '$distRoot' --workpath '$workRoot'"
} else {
    ''
}
$workerScript = @"
Set-Location -LiteralPath '$projectRoot'
& '$python' -m PyInstaller --noconfirm $candidateArguments JARVIS-GUI.spec *> '$logPath'
exit `$LASTEXITCODE
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($workerScript))
$worker = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded
) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru

$previousCpu = Get-TreeCpuSeconds -RootId $worker.Id
$previousPoll = Get-Date
$lowCpuPolls = 0

while (-not $worker.HasExited) {
    Start-Sleep -Seconds $PollSeconds
    $worker.Refresh()
    if ($worker.HasExited) {
        break
    }

    $now = Get-Date
    $currentCpu = Get-TreeCpuSeconds -RootId $worker.Id
    $elapsed = [math]::Max(($now - $previousPoll).TotalSeconds, 1)
    $cpuPercent = (($currentCpu - $previousCpu) / ($elapsed * $logicalProcessors)) * 100
    $previousCpu = $currentCpu
    $previousPoll = $now

    if ($cpuPercent -lt 2.0) {
        $lowCpuPolls++
    } else {
        $lowCpuPolls = 0
    }

    $logAgeMinutes = if (Test-Path -LiteralPath $logPath) {
        ($now - (Get-Item -LiteralPath $logPath).LastWriteTime).TotalMinutes
    } else {
        ($now - $started).TotalMinutes
    }

    if ($logAgeMinutes -ge $StaleMinutes -and $lowCpuPolls -ge 2) {
        Stop-ProcessTree -RootId $worker.Id
        Add-Content -LiteralPath $logPath -Value "WATCHDOG STALLED: log stale for $([math]::Round($logAgeMinutes, 2)) minutes; CPU $([math]::Round($cpuPercent, 2))%."
        Save-Status -Status 'STALLED' -Reason 'Log unchanged for five minutes with CPU below two percent for two polls.' -ExitCode 42
        exit 42
    }

    if ($stopwatch.Elapsed.TotalMinutes -ge $TimeoutMinutes) {
        Stop-ProcessTree -RootId $worker.Id
        Add-Content -LiteralPath $logPath -Value "WATCHDOG TIMEOUT: exceeded $TimeoutMinutes minutes."
        Save-Status -Status 'TIMEOUT' -Reason "Build exceeded $TimeoutMinutes minutes." -ExitCode 43
        exit 43
    }
}

$worker.WaitForExit()
if ($worker.ExitCode -ne 0) {
    Save-Status -Status 'FAILED' -Reason "PyInstaller exited with code $($worker.ExitCode)." -ExitCode $worker.ExitCode
    exit $worker.ExitCode
}
if (-not (Test-Path -LiteralPath $exePath)) {
    Save-Status -Status 'FAILED' -Reason 'PyInstaller returned success but the executable is missing.' -ExitCode 44
    exit 44
}

Save-Status -Status 'OK' -Reason 'Onedir build completed successfully.' -ExitCode 0
exit 0
