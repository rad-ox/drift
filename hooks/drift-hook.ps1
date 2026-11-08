# Universal vendor-agnostic DRIFT lifecycle hook for Windows native agents.
# Supports SessionStart (sessionStart) and Stop (agentStop) payloads across
# Copilot, Claude, Codex, Gemini and Cursor. Fast-exits outside DRIFT areas.
# Context boundary: these payloads carry no trusted task attribution or prompt
# identity. Stop diagnostics keep the conservative area check, state that task
# relevance is unknown, and deduplicate one unchanged diagnostic per host
# session (when supplied) and area; a changed diagnostic reopens it.
[CmdletBinding()]
param(
    [string]$Mode = ''
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'SilentlyContinue'

$payloadText = ''
if ([Console]::IsInputRedirected) {
    $payloadText = [Console]::In.ReadToEnd()
}
$payload = $null
if ($payloadText -and $payloadText.Trim()) {
    try { $payload = $payloadText | ConvertFrom-Json } catch { $payload = $null }
}

$workDir = $PWD.Path
if ($payload -and $payload.PSObject.Properties['cwd'] -and $payload.cwd) {
    $workDir = [string]$payload.cwd
}
if (-not (Test-Path -LiteralPath $workDir -PathType Container)) { exit 0 }

$area = $null
$cur = (Resolve-Path -LiteralPath $workDir).Path
while ($cur) {
    $cfg = [IO.Path]::Combine($cur, '.drift', 'config.toml')
    if (Test-Path -LiteralPath $cfg -PathType Leaf) {
        $area = $cur
        break
    }
    if (Test-Path -LiteralPath ([IO.Path]::Combine($cur, '.git'))) { break }
    $parent = Split-Path -Parent $cur
    if (-not $parent -or $parent -eq $cur) { break }
    $cur = $parent
}
if (-not $area) { exit 0 }

$localData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [IO.Path]::Combine([string]$HOME, 'AppData', 'Local') }
$candidates = @(
    $env:DRIFT_CLI,
    ([IO.Path]::Combine($PSScriptRoot, '..', 'bin', 'drift.exe')),
    ([IO.Path]::Combine($localData, 'Programs', 'drift', 'bin', 'drift.exe'))
)
$cmd = Get-Command 'drift.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($cmd) { $candidates += $cmd.Source }

$driftExe = $null
foreach ($cand in $candidates) {
    if ($cand -and (Test-Path -LiteralPath $cand -PathType Leaf)) {
        $driftExe = $cand
        break
    }
}
if (-not $driftExe) { exit 0 }

$eventName = ''
if ($payload) {
    if ($payload.PSObject.Properties['hook_event_name'] -and $payload.hook_event_name) {
        $eventName = [string]$payload.hook_event_name
    } elseif ($payload.PSObject.Properties['hookEventName'] -and $payload.hookEventName) {
        $eventName = [string]$payload.hookEventName
    }
}
if (-not $eventName) {
    if ($Mode -match '^(?i)(stop|agentstop)$') { $eventName = 'Stop' }
    else { $eventName = 'SessionStart' }
}
$norm = ($eventName.ToLowerInvariant() -replace '[_-]', '')
$contractsDir = [IO.Path]::Combine($area, '.drift', 'contracts')
$session = ''
foreach ($key in @('session_id', 'sessionId')) {
    if (-not $session -and $payload -and $payload.PSObject.Properties[$key] -and $payload.$key) { $session = [string]$payload.$key }
}
$turn = ''
foreach ($key in @('prompt_id', 'promptId', 'turn_id', 'turnId', 'interaction_id', 'interactionId')) {
    if (-not $turn -and $payload -and $payload.PSObject.Properties[$key] -and $payload.$key) { $turn = [string]$payload.$key }
}
$sha = [Security.Cryptography.SHA256]::Create()
$hash = { param([string]$s) -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($s)) | ForEach-Object { $_.ToString('x2') }) }
$baseKey = (& $hash "${area}:$session").Substring(0, 16)

if ($norm -in @('userpromptsubmit', 'userpromptsubmitted')) {
    Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Filter "drift-stop-check-${baseKey}*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    exit 0
}

if ($norm -in @('sessionstart', 'startup', 'resume', 'beforeagentstart')) {
    if ($norm -eq 'beforeagentstart') {
        Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Filter "drift-stop-check-${baseKey}*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    }
    $summary = "DRIFT area active at $area."
    if (Test-Path -LiteralPath $contractsDir -PathType Container) {
        $stLines = & $driftExe 'status' $contractsDir 2>$null
        if ($stLines) {
            $stFlat = (($stLines -join ' ') -replace '\s+', ' ').Trim()
            if ($stFlat) { $summary = "$summary $stFlat." }
        }
    }
    $releaseDir = Join-Path $PSScriptRoot 'release'
    if ($norm -ne 'beforeagentstart' -and $env:DRIFT_UPDATE_CHECK -ne '0' -and
        (Test-Path -LiteralPath $releaseDir -PathType Container)) {
        $checker = Join-Path $releaseDir 'check.ps1'
        if (Test-Path -LiteralPath $checker -PathType Leaf) {
            $notice = & $checker -DriftExe $driftExe
            if ($notice) { $summary = "$summary $notice" }
        } else {
            [Console]::Error.WriteLine('drift: release check unavailable (component missing); continuing without an update verdict.')
        }
    }
    if ($env:DRIFT_EDITION -eq 'free') {
        $msg = "$summary For read-only Q&A or explanations that do not edit code or contracts, answer directly without loading DRIFT skills. When changing code or contracts in DRIFT Free, use drift check, drift fmt, drift review --brief, drift approve --by <owner>, drift prove, and drift gate."
    } else {
        $msg = "$summary For read-only Q&A or explanations that do not edit code or contracts, answer directly without loading DRIFT skills or writing recall cards. When changing code or contracts, follow the drift skill: (0) Orient first with drift recall query '<expr>' (e.g. 'feature @') before exploratory grep/view; on a MISS during contract/code work, record the discovered capsule in .drift-work/recall.jsonl. (1) Behaviour unchanged on covered code (bugfix/refactor/test hardening): 0 human stops, use drift select --changed and drift gate --base. On uncovered code (0 matching contracts), a DRIFT split/refactor is a Baseline Carve-out: scaffold the contract(s) (drift new --from-recall --code), bind proof tests, and run drift review --brief instead of ending with no contract. (2) New or changed behaviour across multiple slices (Wave): use 1 cohesive contract for uniform dispatch/handler splits, or N contracts when slices have distinct rules (<path>#<symbol> on shared files, decide_by = `"execution`" for non-blocking details), run 1 batch drift review .drift/contracts --brief --base, wait ONCE for owner drift approve .drift/contracts --by <owner>, then execute all slices in parallel via drift plan --pack ready. Never piggyback new feature assertions onto existing approved cases."
    }
    $out = @{ additionalContext = $msg } | ConvertTo-Json -Compress
    Write-Output $out
    exit 0
}

if ($norm -in @('stop', 'agentstop', 'afteragent')) {
    if ($payload -and $payload.PSObject.Properties['stop_hook_active'] -and $payload.stop_hook_active -eq $true) {
        [Console]::Error.WriteLine('drift: continued stop; the previous DRIFT outcome was not re-evaluated and is not treated as passing.')
        exit 0
    }
    $stampName = if ($turn) { "drift-stop-check-${baseKey}-" + (& $hash $turn).Substring(0, 12) } else { "drift-stop-check-${baseKey}" }
    $stampFile = [IO.Path]::Combine([IO.Path]::GetTempPath(), $stampName)
    $driftDir = [IO.Path]::Combine($area, '.drift')
    $checkCode = 0
    $stdout = ''
    $stderr = ''
    try {
        $lines = @(& $driftExe 'check' $driftDir '--json' 2>&1)
        $checkCode = $LASTEXITCODE
        $stdout = ($lines | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] } | ForEach-Object { "$_" }) -join "`n"
        $stderr = ($lines | Where-Object { $_ -is [Management.Automation.ErrorRecord] } | ForEach-Object { "$_" }) -join "`n"
    } catch {
        $checkCode = 127
        $stderr = "$_"
    }
    if ($checkCode -eq 0) {
        Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Filter "drift-stop-check-${baseKey}*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    } else {
        $fingerprint = & $hash "${checkCode}:${stdout}:$stderr"
        $last = ''
        if (Test-Path -LiteralPath $stampFile -PathType Leaf) { $last = ([IO.File]::ReadAllText($stampFile)).Trim() }
        if ($last -eq $fingerprint) {
            [Console]::Error.WriteLine('drift: the same DRIFT area diagnostic is still unresolved; not repeated to avoid a correction loop. It is not treated as passing.')
            exit 0
        }
        try { [IO.File]::WriteAllText($stampFile, $fingerprint) } catch { }
        $field = { param($o, [string]$n) if ($o -and $o.PSObject.Properties[$n]) { [string]$o.$n } else { '' } }
        if ($checkCode -eq 1) {
            $count = 0
            $first = $null
            $firstFile = ''
            try {
                $report = $stdout | ConvertFrom-Json
                foreach ($entry in @($report.files)) {
                    foreach ($finding in @($entry.findings)) {
                        $count++
                        if (-not $first) { $first = $finding; $firstFile = & $field $entry 'file' }
                    }
                }
            } catch { }
            $code = & $field $first 'code'
            $where = & $field $first 'path'
            if ($where) { $where = " ($where)" }
            $reason = "DRIFT area check found $count finding(s) in $driftDir; relevance to the current task is unknown (no trusted task attribution). First: $firstFile${where}: $code $(& $field $first 'message'). Next: if this task changed that file, run drift explain $code and fix it; otherwise report it without editing unrelated contracts. The full-area check remains required before delivery."
        } else {
            $cause = @(("$stderr`n$stdout") -split "`n" | Where-Object { $_.Trim() })[0]
            if (-not $cause) { $cause = 'no diagnostic' }
            if ($cause.Length -gt 200) { $cause = $cause.Substring(0, 200) }
            $reason = "DRIFT area check could not run in $driftDir (exit ${checkCode}: invocation, input or environment): $cause. Next: run drift check $driftDir to inspect the tooling or input error; formatting contracts will not fix it. No check verdict is available."
        }
        Write-Output (@{ decision = 'block'; reason = $reason } | ConvertTo-Json -Compress)
        exit 0
    }
    $gitCmd = Get-Command 'git' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($env:DRIFT_EDITION -ne 'free' -and $gitCmd) {
        $porcelain = & $gitCmd.Source -C $area -c core.quotepath=false status --porcelain --untracked-files=normal 2>$null
        $changed = [System.Collections.Generic.List[string]]::new()
        foreach ($ln in $porcelain) {
            if ($ln -and $ln.Length -ge 4 -and $ln[0] -ne 'D' -and $ln[1] -ne 'D') {
                $f = $ln.Substring(3).Trim()
                if (($ln[0] -in @('R', 'C') -or $ln[1] -in @('R', 'C')) -and $f -match ' -> ') {
                    $f = ($f -split ' -> ')[-1].Trim()
                }
                $f = $f.Trim('"')
                if ($f -and $f -notmatch '^\.drift/' -and $f -match '\.(v|java|kt|js|mjs|ts|tsx|py|go|rs)$') {
                    $fullF = [IO.Path]::Combine($area, ($f -replace '/', [IO.Path]::DirectorySeparatorChar))
                    if (Test-Path -LiteralPath $fullF -PathType Leaf) {
                        $changed.Add($f)
                        if ($changed.Count -ge 25) { break }
                    }
                }
            }
        }
        if ($changed.Count -gt 0) {
            $impFlat = ''
            $impOk = $true
            if (Test-Path -LiteralPath $contractsDir -PathType Container) {
                $impArgs = [System.Collections.Generic.List[string]]::new()
                $impArgs.Add('impact')
                $impArgs.Add($contractsDir)
                foreach ($cf in $changed) { $impArgs.Add('--code'); $impArgs.Add($cf) }
                $impArgs.Add('--json')
                $impOut = & $driftExe @impArgs 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $impFlat = (($impOut -join '') -replace '\s+', '')
                } else {
                    $impOk = $false
                }
            }
            if ($impOk) {
                if (-not $impFlat) {
                    $impFlat = '{"contracts":[],"unmatched_code":["uncontracted"]}'
                }
                if ($impFlat -match '"unmatched_code":\["') {
                    $dirtyContracts = & $gitCmd.Source -C $area status --porcelain --untracked-files=normal -- .drift/contracts 2>$null
                    if ($dirtyContracts -or $impFlat -match '"contracts":\[\]') {
                        $stampId = (& $hash ("${area}:" + ($changed -join "`n"))).Substring(0, 16)
                        $unownedStamp = [IO.Path]::Combine([IO.Path]::GetTempPath(), "drift-stop-$stampId")
                        if (-not (Test-Path -LiteralPath $unownedStamp -PathType Leaf)) {
                            try { [IO.File]::WriteAllText($unownedStamp, '') } catch { }
                            $out = @{
                                decision = 'block'
                                reason   = "Changed source files in $area are not covered by any contract scope.code (unmatched_code); whether this task owns them is unknown (working-tree evidence, not task attribution). Next: if this task changed them, scaffold the baseline contract(s) (drift new --from-recall --code) or run drift sweep --root $area --sync-scope; otherwise report them and leave them unchanged."
                            } | ConvertTo-Json -Compress
                            Write-Output $out
                        }
                    }
                }
            }
        }
    }
}
exit 0
