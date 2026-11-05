# Universal vendor-agnostic DRIFT lifecycle hook for Windows native agents.
# Supports SessionStart (sessionStart) and Stop (agentStop) payloads across
# Copilot, Claude, Codex, Gemini and Cursor. Fast-exits outside DRIFT areas.
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

if ($norm -in @('sessionstart', 'startup', 'resume', 'beforeagentstart')) {
    $summary = "DRIFT area active at $area."
    if (Test-Path -LiteralPath $contractsDir -PathType Container) {
        $stLines = & $driftExe 'status' $contractsDir 2>$null
        if ($stLines) {
            $stFlat = (($stLines -join ' ') -replace '\s+', ' ').Trim()
            if ($stFlat) { $summary = "$summary $stFlat." }
        }
    }
    $msg = "$summary For read-only Q&A or explanations that do not edit code or contracts, answer directly without loading DRIFT skills or writing recall cards. When changing code or contracts, follow the drift skill: (0) Orient first with drift impact --recall '<expr>' (e.g. 'feature @') before exploratory grep/view; on a MISS during contract/code work, record the discovered capsule in .drift-work/recall.jsonl. (1) Behaviour unchanged on covered code (bugfix/refactor/test hardening): 0 human stops, use drift select --changed and drift gate --base. On uncovered code (0 matching contracts), a DRIFT split/refactor is a Baseline Carve-out: scaffold the contract(s) (drift new --from-recall --code), bind proof tests, and run drift review --brief instead of ending with no contract. (2) New or changed behaviour across multiple slices (Wave): use 1 cohesive contract for uniform dispatch/handler splits, or N contracts when slices have distinct rules (<path>#<symbol> on shared files, decide_by = `"execution`" for non-blocking details), run 1 batch drift review .drift/contracts --brief --base, wait ONCE for owner drift approve .drift/contracts --by <owner>, then execute all slices in parallel via drift impact --schedule --pack ready. Never piggyback new feature assertions onto existing approved cases."
    $out = @{ additionalContext = $msg } | ConvertTo-Json -Compress
    Write-Output $out
    exit 0
}

if ($norm -in @('stop', 'agentstop', 'afteragent')) {
    if ($payload -and $payload.PSObject.Properties['stop_hook_active'] -and $payload.stop_hook_active -eq $true) {
        exit 0
    }
    & $driftExe 'check' ([IO.Path]::Combine($area, '.drift')) '--json' *> $null
    if ($LASTEXITCODE -ne 0) {
        $out = @{
            decision = 'block'
            reason   = "DRIFT check reported findings in $area\.drift. Run drift fmt and drift check --json before finishing."
        } | ConvertTo-Json -Compress
        Write-Output $out
        exit 0
    }
    $gitCmd = Get-Command 'git' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($gitCmd) {
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
            if (Test-Path -LiteralPath $contractsDir -PathType Container) {
                $impArgs = [System.Collections.Generic.List[string]]::new()
                $impArgs.Add('impact')
                $impArgs.Add($contractsDir)
                foreach ($cf in $changed) { $impArgs.Add('--code'); $impArgs.Add($cf) }
                $impArgs.Add('--json')
                $impFlat = ((& $driftExe @impArgs 2>$null) -join '') -replace '\s+', ''
            }
            if (-not $impFlat) {
                $impFlat = '{"contracts":[],"unmatched_code":["uncontracted"]}'
            }
            if ($impFlat -match '"unmatched_code":\["') {
                $dirtyContracts = & $gitCmd.Source -C $area status --porcelain --untracked-files=normal -- .drift/contracts 2>$null
                if ($dirtyContracts -or $impFlat -match '"contracts":\[\]') {
                    $out = @{
                        decision = 'block'
                        reason   = "DRIFT impact detected changed source files in $area not covered by any contract scope.code (unmatched_code). Scaffold the baseline contract(s) (drift new --from-recall --code) or run drift sweep --root $area --sync-scope instead of piggybacking on unrelated cases."
                    } | ConvertTo-Json -Compress
                    Write-Output $out
                }
            }
        }
    }
}
exit 0
