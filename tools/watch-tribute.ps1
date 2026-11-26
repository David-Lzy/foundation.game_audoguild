#Requires -Version 5.1
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [Parameter(ParameterSetName = 'Run', Mandatory)]
    [string]$Captain,
    [Parameter(ParameterSetName = 'Run')]
    [ValidateRange(1, 99)][int]$Level = 3,
    [Parameter(ParameterSetName = 'Run')]
    [ValidateRange(1, 10)][int]$BatchSize = 8,
    [Parameter(ParameterSetName = 'Run')]
    [ValidateRange(0.01, 720)][double]$Hours = 2,
    [Parameter(ParameterSetName = 'Run')]
    [ValidateRange(60, 1800)][int]$ResultTimeout = 480,
    [Parameter(ParameterSetName = 'Observe', Mandatory)]
    [ValidateRange(1, 2147483647)][int]$ObservePid,
    [Parameter(ParameterSetName = 'Observe', Mandatory)]
    [string]$EventLog,
    [Parameter(ParameterSetName = 'Observe')]
    [ValidateRange(1, 86400)][int]$StallSeconds = 630,
    [ValidateRange(1, 30)][int]$PollSeconds = 5
)

$ErrorActionPreference = 'Stop'
$reportPath = $null
$worker = $null
$deadlineSeconds = $null

function Complete-Watch([System.Collections.IDictionary]$Record, [int]$ExitCode) {
    $Record['monitor'] = 'done'
    $Record['observed_utc'] = [DateTimeOffset]::UtcNow.ToString('o')
    $json = $Record | ConvertTo-Json -Depth 8 -Compress
    if ($reportPath) {
        try {
            $encoding = [System.Text.UTF8Encoding]::new($false)
            $bytes = $encoding.GetBytes($json + [Environment]::NewLine)
            $stream = [IO.File]::Open($reportPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
            try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
        } catch {
            Write-Warning ("Could not write monitor report: " + $_.Exception.Message)
        }
    }
    Write-Output $json
    exit $ExitCode
}

if ($PSCmdlet.ParameterSetName -eq 'Run') {
    $Captain = $Captain.Trim()
    if ($Captain.Length -gt 26 -or $Captain -notmatch '[\p{L}\p{Nd}]' -or
        $Captain -match '^\[|[\x00-\x1f"\\]') {
        throw 'Enter the exact game nickname, without an alliance tag or quoting characters.'
    }
    $hklm = [Microsoft.Win32.RegistryKey]::OpenBaseKey('LocalMachine', 'Registry64')
    $key = $hklm.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall\FoundationTributeRunner')
    try {
        if (-not $key) { throw 'The installed Foundation Tribute Runner was not found.' }
        $install = [string]$key.GetValue('InstallLocation')
        $version = [string]$key.GetValue('DisplayVersion')
    } finally {
        if ($key) { $key.Dispose() }
        $hklm.Dispose()
    }
    if ($install -notmatch '^[A-Za-z]:\\') { throw 'The registered installation path is invalid.' }
    $exe = Get-Item -LiteralPath (Join-Path $install 'FoundationTributeRunner.exe')
    if ($exe.PSIsContainer -or ($exe.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The registered executable is not a regular file.'
    }
    $sessionId = (Get-Process -Id $PID).SessionId
    $other = @(Get-CimInstance Win32_Process | Where-Object {
        $_.SessionId -eq $sessionId -and
        ($_.Name -eq 'FoundationTributeRunner.exe' -or
         ($_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'tribute[-_](cycle|loop).+--execute'))
    })
    if ($other.Count) { throw 'A runner is already open in this session; not starting another.' }

    $run = 'tribute-cycle-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
    $root = Join-Path $env:LOCALAPPDATA 'FoundationTributeRunner\artifacts\runs'
    $dir = Join-Path $root $run
    New-Item -ItemType Directory -Path $dir | Out-Null
    $EventLog = Join-Path $dir 'events.jsonl'
    $reportPath = Join-Path $dir 'monitor-result.json'
    $StallSeconds = $ResultTimeout + 150
    $deadlineSeconds = $Hours * 3600 + $StallSeconds
    Write-Output ([ordered]@{ monitor = 'starting'; version = $version; hours = $Hours
        event_log = $EventLog; result_file = $reportPath } | ConvertTo-Json -Compress)
    $hoursText = $Hours.ToString([Globalization.CultureInfo]::InvariantCulture)
    $options = @('tribute-cycle', ('"--captain={0}"' -f $Captain), '--level', "$Level",
        '--batch-size', "$BatchSize", '--result-timeout', "$ResultTimeout", '--hours', $hoursText,
        '--execute', '--event-log', ('"{0}"' -f $EventLog))
    try {
        $worker = Start-Process -FilePath $exe.FullName -ArgumentList $options -Verb RunAs `
            -WorkingDirectory $install -WindowStyle Hidden -PassThru
    } catch {
        Complete-Watch ([ordered]@{ status = 'launch_failed'; detail = $_.Exception.Message
            event_log = $EventLog }) 2
    }
    $ObservePid = $worker.Id
} else {
    $EventLog = [IO.Path]::GetFullPath($EventLog)
    $worker = Get-Process -Id $ObservePid -ErrorAction SilentlyContinue
}

Write-Output ([ordered]@{ monitor = 'watching'; worker_pid = $ObservePid; event_log = $EventLog
    stall_seconds = $StallSeconds } | ConvertTo-Json -Compress)
$elapsed = [Diagnostics.Stopwatch]::StartNew()
$sinceEvent = [Diagnostics.Stopwatch]::StartNew()
$previousLength = -1L
$processed = 0
$submitted = 0
$confirmed = 0
$finishing = $false
$lastEvent = $null
$seenExit = $false
$logError = $null
while ($true) {
    try {
        $file = Get-Item -LiteralPath $EventLog -ErrorAction SilentlyContinue
        if ($file -and $file.Length -ne $previousLength) {
            $lines = @(Get-Content -LiteralPath $EventLog -Encoding UTF8)
            if ($lines.Count -lt $processed) { throw 'The run log was truncated.' }
            $previousLength = $file.Length
            while ($processed -lt $lines.Count) {
                try { $event = ConvertFrom-Json -InputObject $lines[$processed] } catch { break }
                if (-not $event.event) { break }
                $processed++
                $lastEvent = $event
                $sinceEvent.Restart()
                switch ($event.event) {
                    'round_submitted' { $submitted++ }
                    'round_confirmed' { $confirmed++ }
                    'finishing' { $finishing = $true }
                }
            }
        }
        $logError = $null
    } catch { $logError = $_.Exception.Message }

    $alive = $false
    $workerExit = $null
    if ($worker) {
        try {
            $alive = -not $worker.HasExited
            if (-not $alive) { $workerExit = $worker.ExitCode }
        } catch {
            $alive = [bool](Get-Process -Id $ObservePid -ErrorAction SilentlyContinue)
        }
    }
    $status = $null
    $exitCode = 2
    if ($lastEvent.event -eq 'finished') {
        $status = 'finished'
        $exitCode = 0
    } elseif ($lastEvent.event -eq 'stopped') {
        $status = 'stopped'
    } elseif (-not $alive) {
        # Re-read once after exit: the last line can arrive just after the previous read.
        if (-not $seenExit) { $seenExit = $true; $previousLength = -1; continue }
        $status = 'exited_without_terminal_event'
    } elseif ($deadlineSeconds -and -not $finishing -and $elapsed.Elapsed.TotalSeconds -ge $deadlineSeconds) {
        $status = 'deadline_overrun'
        $exitCode = 3
    } elseif ($sinceEvent.Elapsed.TotalSeconds -ge $(if ($lastEvent) { $StallSeconds } else { [math]::Min(60, $StallSeconds) })) {
        $status = 'stalled'
        $exitCode = 3
    }
    if ($status) {
        Complete-Watch ([ordered]@{ status = $status; worker_pid = $ObservePid; worker_alive = $alive
            worker_exit = $workerExit; event_log = $EventLog; submitted = $submitted; confirmed = $confirmed
            pending = [math]::Max(0, $submitted - $confirmed); last_event = $lastEvent; log_error = $logError }) $exitCode
    }
    Start-Sleep -Seconds $PollSeconds
}
