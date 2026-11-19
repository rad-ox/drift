[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RawArgs = @()
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Stop-Broker([string]$Message, [int]$Code = 2) {
    [Console]::Error.WriteLine("drift-ask-ui: $Message")
    exit $Code
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $tmp = "$Path.tmp.$PID"
    [IO.File]::WriteAllText($tmp, $Text, $Utf8NoBom)
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force }
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Test-IsReparse([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $attr = [IO.File]::GetAttributes($Path)
    return (($attr -band [IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Get-LocalConfigPath {
    $localBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [IO.Path]::Combine([string]$HOME, 'AppData', 'Local') }
    $cands = @()
    if ($env:XDG_CONFIG_HOME) { $cands += [IO.Path]::Combine($env:XDG_CONFIG_HOME, 'drift', 'local.toml') }
    $cands += [IO.Path]::Combine([string]$HOME, '.config', 'drift', 'local.toml')
    $cands += [IO.Path]::Combine($localBase, 'drift', 'local.toml')
    foreach ($c in $cands) {
        if (Test-Path -LiteralPath $c -PathType Leaf) {
            if (Test-IsReparse $c) { Stop-Broker 'refusing symlinked or reparse local.toml' 2 }
            return $c
        }
    }
    $def = $cands[$cands.Count - 1]
    if (Test-IsReparse ([IO.Path]::GetDirectoryName($def))) { Stop-Broker 'refusing reparse config directory' 2 }
    return $def
}

function Read-UiConfig {
    $cfgFile = Get-LocalConfigPath
    $res = @{
        mode = 'auto'
        theme = 'auto'
        explicit_mode = $false
        owner = ''
        ssh_sign_key = ''
        quiet_arm_ms = 300
        timeout_s = 0
        renderer = ''
        path = $cfgFile
    }
    if (-not (Test-Path -LiteralPath $cfgFile -PathType Leaf)) { return $res }
    $sec = ''
    foreach ($rawLn in [IO.File]::ReadAllLines($cfgFile, $Utf8NoBom)) {
        $ln = $rawLn.Trim()
        if (-not $ln -or $ln.StartsWith('#')) { continue }
        if ($ln -match '^\[([^\]]+)\]$') { $sec = $Matches[1].Trim(); continue }
        if ($sec -ne 'ui') { continue }
        if ($ln -match '^([A-Za-z0-9_]+)\s*=\s*(.+)$') {
            $k = $Matches[1].Trim()
            $rawValue = $Matches[2].Trim()
            $v = $rawValue
            if ($v -match '^"(.*)"$' -or $v -match "^'(.*)'$") { $v = $Matches[1] }
            if ($k -eq 'mode') { $res.mode = $v; $res.explicit_mode = $true }
            elseif ($k -eq 'theme') { $res.theme = $v.ToLowerInvariant() }
            elseif ($k -eq 'owner') { $res.owner = $v }
            elseif ($k -eq 'ssh_sign_key') { $res.ssh_sign_key = $v }
            elseif ($k -eq 'renderer') { $res.renderer = $v }
            elseif ($k -eq 'quiet_arm_ms') {
                $parsed = 0
                if (-not [int]::TryParse($v, [ref]$parsed)) { Stop-Broker 'quiet_arm_ms must be an integer' 2 }
                $res.quiet_arm_ms = [Math]::Max(50, $parsed)
            }
            elseif ($k -eq 'timeout_s') {
                $parsedT = 0
                $rawTimeout = ($rawValue -split '#', 2)[0].Trim()
                if ($rawTimeout -notmatch '^\+?(?:0|[1-9](?:_?[0-9])*)$' -or
                    -not [int]::TryParse($rawTimeout.Replace('_', ''), [ref]$parsedT)) {
                    Stop-Broker 'timeout_s in local.toml must be an integer from 0 to 2147483647' 2
                }
                $res.timeout_s = $parsedT
            }
        }
    }
    return $res
}

function Save-UiConfigFields([hashtable]$Updates) {
    $cfgFile = Get-LocalConfigPath
    $dir = [IO.Path]::GetDirectoryName($cfgFile)
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    if (Test-IsReparse $dir -or Test-IsReparse $cfgFile) { Stop-Broker 'refusing reparse local.toml' 2 }
    $mtx = New-Object System.Threading.Mutex($false, 'Local\DriftUi_ConfigLock')
    $locked = $false
    try {
        try { $locked = $mtx.WaitOne([TimeSpan]::FromSeconds(10)) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
        $lines = @()
        if (Test-Path -LiteralPath $cfgFile -PathType Leaf) {
            $lines = [IO.File]::ReadAllLines($cfgFile, $Utf8NoBom)
        }
        $out = New-Object System.Collections.Generic.List[string]
        $sec = ''
        $inUi = $false
        $writtenKeys = @{}
        foreach ($rawLn in $lines) {
            $t = $rawLn.Trim()
            if ($t -match '^\[([^\]]+)\]$') {
                if ($inUi) {
                    foreach ($uk in $Updates.Keys) {
                        if (-not $writtenKeys.ContainsKey($uk)) {
                            $esc = ([string]$Updates[$uk]).Replace('\', '\\').Replace('"', '\"')
                            $out.Add("$uk = `"$esc`"")
                            $writtenKeys[$uk] = $true
                        }
                    }
                }
                $sec = $Matches[1].Trim()
                $inUi = ($sec -eq 'ui')
                $out.Add($rawLn)
                continue
            }
            if ($inUi -and $t -notmatch '^#' -and $t -match '^([A-Za-z0-9_]+)\s*=') {
                $k = $Matches[1].Trim()
                if ($Updates.ContainsKey($k)) {
                    $esc = ([string]$Updates[$k]).Replace('\', '\\').Replace('"', '\"')
                    $out.Add("$k = `"$esc`"")
                    $writtenKeys[$k] = $true
                    continue
                }
            }
            $out.Add($rawLn)
        }
        if (-not ($lines | Where-Object { $_.Trim() -eq '[ui]' })) {
            if ($out.Count -gt 0 -and $out[$out.Count - 1] -ne '') { $out.Add('') }
            $out.Add('[ui]')
            foreach ($uk in $Updates.Keys) {
                $esc = ([string]$Updates[$uk]).Replace('\', '\\').Replace('"', '\"')
                $out.Add("$uk = `"$esc`"")
            }
        } elseif ($inUi) {
            foreach ($uk in $Updates.Keys) {
                if (-not $writtenKeys.ContainsKey($uk)) {
                    $esc = ([string]$Updates[$uk]).Replace('\', '\\').Replace('"', '\"')
                    $out.Add("$uk = `"$esc`"")
                }
            }
        }
        Write-Utf8NoBom $cfgFile (($out -join "`n") + "`n")
    } finally {
        if ($locked) { try { $mtx.ReleaseMutex() } catch {} }
        $mtx.Dispose()
    }
    return $cfgFile
}

function Find-AreaRoot([string]$StartDir) {
    $cur = (Resolve-Path -LiteralPath $StartDir).Path
    $gitStop = $null
    while ($true) {
        if ((Test-Path -LiteralPath ([IO.Path]::Combine($cur, '.drift', 'config.toml')) -PathType Leaf) -or
            (Test-Path -LiteralPath ([IO.Path]::Combine($cur, '.drift', 'contracts')) -PathType Container)) {
            return $cur
        }
        if (-not $gitStop -and (Test-Path -LiteralPath ([IO.Path]::Combine($cur, '.git')))) { $gitStop = $cur }
        $parent = [IO.Path]::GetDirectoryName($cur)
        if (-not $parent -or $parent -eq $cur) { return $(if ($gitStop) { $gitStop } else { (Resolve-Path -LiteralPath $StartDir).Path }) }
        $cur = $parent
    }
}

function Ensure-CompiledWpfExe {
    $csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    $csPath = [IO.Path]::Combine($PSScriptRoot, 'DriftUiWin.cs')
    $mfPath = [IO.Path]::Combine($PSScriptRoot, 'app.manifest')
    if (-not (Test-Path -LiteralPath $csc -PathType Leaf) -or -not (Test-Path -LiteralPath $csPath -PathType Leaf) -or -not (Test-Path -LiteralPath $mfPath -PathType Leaf)) {
        return ''
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    $comboBytes = [IO.File]::ReadAllBytes($csPath) + @(0) + [IO.File]::ReadAllBytes($mfPath)
    $h = (-join ($sha.ComputeHash($comboBytes) | ForEach-Object { $_.ToString('x2') })).Substring(0, 12)
    $localBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [IO.Path]::Combine([string]$HOME, 'AppData', 'Local') }
    $binDir = [IO.Path]::Combine($localBase, 'drift', 'bin')
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
    $uiExe = [IO.Path]::Combine($binDir, "drift-ui-win-$h.exe")

    $cmtx = New-Object System.Threading.Mutex($false, "Local\DriftUi_Compile_$h")
    $locked = $false
    try {
        try { $locked = $cmtx.WaitOne([TimeSpan]::FromSeconds(30)) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
        if (-not (Test-Path -LiteralPath $uiExe -PathType Leaf)) {
            $tmpExe = [IO.Path]::Combine($binDir, "build-$PID-$([Guid]::NewGuid().ToString('N').Substring(0,6)).exe")
            $fw = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319'
            & $csc '/nologo' '/optimize+' '/warnaserror+' '/target:winexe' "/win32manifest:$mfPath" `
                "/r:$fw\WPF\WindowsBase.dll" "/r:$fw\WPF\PresentationCore.dll" `
                "/r:$fw\WPF\PresentationFramework.dll" "/r:$fw\System.Xaml.dll" `
                "/r:$fw\System.Runtime.Serialization.dll" "/r:$fw\System.Xml.dll" `
                "/out:$tmpExe" $csPath | Out-Null
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $tmpExe -PathType Leaf)) {
                Remove-Item -LiteralPath $tmpExe -Force -ErrorAction SilentlyContinue
                return ''
            }
            Move-Item -LiteralPath $tmpExe -Destination $uiExe -Force
        }
    } finally {
        if ($locked) { try { $cmtx.ReleaseMutex() } catch {} }
        $cmtx.Dispose()
    }
    & $uiExe '--probe' | Out-Null
    if ($LASTEXITCODE -ne 0) { return '' }
    return $uiExe
}

function Get-HostSuggestedOwner {
    $gitCmd = Get-Command 'git.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($gitCmd) {
        try {
            $psi = New-Object System.Diagnostics.ProcessStartInfo($gitCmd.Source, 'config --global --get user.name')
            $psi.WorkingDirectory = [Environment]::GetFolderPath('UserProfile')
            $psi.UseShellExecute = $false
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.EnvironmentVariables.Remove('GIT_CONFIG_GLOBAL')
            $psi.EnvironmentVariables.Remove('GIT_CONFIG_COUNT')
            $psi.EnvironmentVariables.Remove('GIT_DIR')
            $gp = [System.Diagnostics.Process]::Start($psi)
            $gout = $gp.StandardOutput.ReadToEnd()
            $gp.WaitForExit(2000) | Out-Null
            if ($gp.ExitCode -eq 0 -and $gout -and $gout.Trim()) { return $gout.Trim() }
        } catch {}
    }
    if ([Environment]::UserName) { return [Environment]::UserName }
    return ''
}

function Test-RepoDowngradeOff([string]$AreaPath) {
    $rcfg = [IO.Path]::Combine($AreaPath, '.drift', 'config.toml')
    if (-not (Test-Path -LiteralPath $rcfg -PathType Leaf) -or (Test-IsReparse $rcfg)) { return $false }
    $sec = ''
    foreach ($ln in [IO.File]::ReadAllLines($rcfg, $Utf8NoBom)) {
        $t = $ln.Trim()
        if ($t -match '^\[([^\]]+)\]$') { $sec = $Matches[1].Trim(); continue }
        if ($sec -eq 'ui' -and $t -match '^mode\s*=\s*"?(off|none)"?$') { return $true }
    }
    return $false
}

function Get-WorkspaceIdentity([string]$AreaPath) {
    $full = (Resolve-Path -LiteralPath $AreaPath).Path
    $homeDir = [Environment]::GetFolderPath('UserProfile')
    $compact = if ($homeDir -and $full.StartsWith($homeDir, [StringComparison]::OrdinalIgnoreCase)) { '~' + $full.Substring($homeDir.Length) } else { $full }
    $proj = Split-Path -Leaf $full
    $wt = $proj
    $branch = ''
    $isWt = $false
    $gitCmd = Get-Command 'git.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($gitCmd) {
        try {
            $br = (& $gitCmd.Source '-C' $full 'rev-parse' '--abbrev-ref' 'HEAD' 2>$null) -join ''
            if ($LASTEXITCODE -eq 0 -and $br.Trim() -and $br.Trim() -ne 'HEAD') { $branch = $br.Trim() }
            $dirs = @(& $gitCmd.Source '-C' $full 'rev-parse' '--git-dir' '--git-common-dir' 2>$null)
            if ($LASTEXITCODE -eq 0 -and $dirs.Count -ge 2) {
                $gd = if ([IO.Path]::IsPathRooted($dirs[0])) { $dirs[0] } else { [IO.Path]::GetFullPath([IO.Path]::Combine($full, $dirs[0])) }
                $cd = if ([IO.Path]::IsPathRooted($dirs[1])) { $dirs[1] } else { [IO.Path]::GetFullPath([IO.Path]::Combine($full, $dirs[1])) }
                if (-not [string]::Equals($gd, $cd, [StringComparison]::OrdinalIgnoreCase)) { $isWt = $true }
                if ((Split-Path -Leaf $cd) -eq '.git') {
                    $pName = Split-Path -Leaf (Split-Path -Parent $cd)
                    if ($pName) { $proj = $pName }
                }
            }
        } catch {}
    }
    return @{ project_name = $proj; worktree_name = $wt; is_linked_worktree = $isWt; git_branch = $branch; workspace_path = $compact }
}

function Get-TargetStates([string]$DriftBin, [string]$AreaPath, [string[]]$Targets) {
    $map = @{}
    if (-not $Targets -or $Targets.Count -eq 0) { return $map }
    Push-Location -LiteralPath $AreaPath
    try {
        $stArgs = @('status') + $Targets + @('--detail', 'guided', '--json')
        $stRaw = (& $DriftBin @stArgs 2>$null) -join "`n"
        if ($LASTEXITCODE -in @(0, 1) -and $stRaw.Trim()) {
            $stDoc = $stRaw | ConvertFrom-Json
            foreach ($sc in @($stDoc.contracts)) {
                if (-not $sc) { continue }
                $p = if ($sc.file) { [string]$sc.file } else { [string]$sc.id }
                $map[$p] = [string]$sc.approval
            }
        }
    } catch {} finally { Pop-Location }
    return $map
}

if ($RawArgs.Count -eq 1 -and $RawArgs[0] -eq '--off') {
    $p = Save-UiConfigFields @{ mode = 'off' }
    Write-Output (@{ config_file = $p; mode = 'off'; schema = 'drift.ui-prefs/1'; status = 'ok' } | ConvertTo-Json -Compress)
    exit 0
}
if ($RawArgs.Count -eq 1 -and $RawArgs[0] -eq '--on') {
    $p = Save-UiConfigFields @{ mode = 'auto' }
    Write-Output (@{ config_file = $p; mode = 'auto'; schema = 'drift.ui-prefs/1'; status = 'ok' } | ConvertTo-Json -Compress)
    exit 0
}
if ($RawArgs.Count -eq 1 -and $RawArgs[0] -eq '--status') {
    $cfg = Read-UiConfig
    $envOff = ($env:DRIFT_UI -and $env:DRIFT_UI.Trim().ToLowerInvariant() -in @('off', '0', 'false', 'none'))
    $effMode = if ($envOff) { 'off' } else { $cfg.mode }
    $exe = if ($effMode -in @('', 'off', 'none')) { '' } else { Ensure-CompiledWpfExe }
    Write-Output (@{
        backend = $(if ($exe) { 'win-native' } else { 'fallback' })
        deciding_layer = $(if ($envOff) { 'DRIFT_UI' } elseif ($cfg.explicit_mode) { 'local_toml' } else { 'default_auto' })
        desktop_available = [bool]$exe
        effective_mode = $effMode
        enrolled_owner = $cfg.owner
        os = 'Windows'
        schema = 'drift.ui-prefs/1'
        theme = $cfg.theme
    } | ConvertTo-Json -Compress)
    exit 0
}

$rtBase = [IO.Path]::Combine([IO.Path]::GetTempPath(), "drift-ui-$env:USERNAME")
New-Item -ItemType Directory -Force -Path $rtBase | Out-Null

if ($RawArgs.Count -eq 2 -and $RawArgs[0] -eq '--cancel') {
    $cid = $RawArgs[1].Trim()
    if (-not $cid -or $cid.Contains('/') -or $cid.Contains('\') -or $cid.Contains('..')) { Stop-Broker 'invalid request_id for --cancel' 2 }
    $cDir = [IO.Path]::Combine($rtBase, 'requests', $cid)
    New-Item -ItemType Directory -Force -Path $cDir | Out-Null
    Write-Utf8NoBom ([IO.Path]::Combine($cDir, 'state')) "cancelled`n"
    Remove-Item -LiteralPath ([IO.Path]::Combine($cDir, 'sentinel')) -Force -ErrorAction SilentlyContinue
    Write-Output (@{ approval_writes = 0; request_id = $cid; schema = 'drift.ui-result/1'; status = 'cancelled' } | ConvertTo-Json -Compress)
    exit 0
}

$Selectors = @()
foreach ($a in $RawArgs) {
    if ($a.StartsWith('-')) { Stop-Broker "unsupported option: $a" 2 }
    if ($a -match '\.json$') { Stop-Broker 'refusing pre-rendered JSON input; pass contract or directory selectors' 2 }
    $Selectors += $a
}
if ($Selectors.Count -eq 0) { $Selectors = @('.drift/contracts') }

$cfg = Read-UiConfig
if ($cfg.mode -notin @('', 'off', 'none', 'auto', 'win-native', 'wsl-popup', 'web-deck', 'custom')) {
    Stop-Broker "unsupported [ui].mode '$($cfg.mode)'" 2
}
if ($cfg.theme -notin @('auto', 'dark', 'light')) {
    Stop-Broker "unsupported [ui].theme '$($cfg.theme)'" 2
}

$area = Find-AreaRoot $PWD.Path
$driftExe = $env:DRIFT_CLI
if (-not $driftExe) {
    foreach ($cand in @(
        ([IO.Path]::Combine($PSScriptRoot, '..', 'bin', 'drift.exe')),
        ([IO.Path]::Combine($PSScriptRoot, '..', '..', 'bin', 'drift.exe'))
    )) {
        if (Test-Path -LiteralPath $cand -PathType Leaf) { $driftExe = $cand; break }
    }
    if (-not $driftExe) {
        $cmd = Get-Command 'drift.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { $driftExe = $cmd.Source }
    }
}
if (-not $driftExe) { Stop-Broker 'cannot locate drift.exe' 2 }

Push-Location -LiteralPath $area
try {
    $verOut = & $driftExe 'version' '--json'
    if ($LASTEXITCODE -ne 0) { Stop-Broker 'drift version --json failed' 2 }
    $verDoc = ($verOut -join "`n") | ConvertFrom-Json
    $caps = @($verDoc.capabilities)
    $edition = if ($verDoc.PSObject.Properties['effective_edition'] -and $verDoc.effective_edition) { [string]$verDoc.effective_edition } else { 'free' }
    if ($env:DRIFT_EDITION -eq 'free') { $caps = @(); $edition = 'free' }

    $hasHead = $false
    $gitCmd = Get-Command 'git.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($gitCmd) {
        & $gitCmd.Source 'rev-parse' '--verify' 'HEAD' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $hasHead = $true }
    }

    $revArgs = @('review') + $Selectors
    if (($caps -contains 'incremental_baseline') -and $hasHead) {
        $revArgs += @('--base', 'HEAD', '--delta')
    }
    $revArgs += @('--detail', 'guided', '--as', 'json')
    $revRaw = (& $driftExe @revArgs) -join "`n"
    if ($LASTEXITCODE -eq 2) { Stop-Broker 'drift review failed' 2 }
    $doc = $revRaw | ConvertFrom-Json
} finally {
    Pop-Location
}

$snap = if ($doc.PSObject.Properties['review_snapshot']) { $doc.review_snapshot } else { $null }
$revRef = if ($snap -and $snap.PSObject.Properties['review_ref']) { [string]$snap.review_ref } else { '' }
$attemptId = ([Guid]::NewGuid().ToString('N').Substring(0, 20))

function Invoke-Fallback([string]$Reason) {
    $fbSnap = [IO.Path]::Combine($rtBase, "fallback-$attemptId.review.json")
    Write-Utf8NoBom $fbSnap $revRaw
    $who = if ($cfg.owner) { $cfg.owner } else { '<owner>' }
    $nextCmd = if ($revRef) { "drift approve --reviewed `"$fbSnap`" --expect-review $revRef --by `"$who`"" } else { '' }
    $payload = @{
        approval_writes = 0
        next_command = $nextCmd
        reason = $Reason
        request_id = $attemptId
        review_ref = $revRef
        schema = 'drift.ui-result/1'
        snapshot_file = $fbSnap
        status = 'fallback'
    }
    Write-Output ($payload | ConvertTo-Json -Compress)
    if ($nextCmd) { [Console]::Error.WriteLine("Next command: $nextCmd") }
    exit 10
}

if ($env:DRIFT_UI -and $env:DRIFT_UI.Trim().ToLowerInvariant() -in @('off', '0', 'false', 'none')) { Invoke-Fallback 'ui_disabled_env' }
if (Test-RepoDowngradeOff $area) { Invoke-Fallback 'ui_disabled_repo' }
if ($cfg.mode -in @('', 'off', 'none')) { Invoke-Fallback 'ui_disabled' }
if ($cfg.mode -eq 'web-deck') { Invoke-Fallback 'web_deck_requires_posix_or_python_entrypoint' }
if ($cfg.mode -ne 'custom' -and (($env:CI -and $env:CI.ToLowerInvariant() -in @('1', 'true')) -or $env:SSH_CONNECTION)) { Invoke-Fallback 'headless_or_ci' }

if ([string]$doc.next_actor -ne 'user') {
    Write-Output (@{
        approval_writes = 0
        next_actor = $doc.next_actor
        next_command = $doc.next_command
        request_id = $attemptId
        schema = 'drift.ui-result/1'
        status = 'no_user_action'
    } | ConvertTo-Json -Compress)
    exit $(if ($doc.ok) { 0 } else { 1 })
}

$runnerExe = ''
if ($cfg.mode -eq 'custom') {
    if (-not $cfg.renderer -or -not (Test-Path -LiteralPath $cfg.renderer -PathType Leaf)) { Stop-Broker '[ui].renderer missing' 2 }
    $runnerExe = $cfg.renderer
} else {
    $runnerExe = Ensure-CompiledWpfExe
    if (-not $runnerExe) { Invoke-Fallback 'windows_desktop_unavailable' }
}

$reqDir = [IO.Path]::Combine($rtBase, 'requests', $attemptId)
New-Item -ItemType Directory -Force -Path $reqDir | Out-Null
$stateFile = [IO.Path]::Combine($reqDir, 'state')
$sentinelFile = [IO.Path]::Combine($reqDir, 'sentinel')
$snapFile = [IO.Path]::Combine($reqDir, 'review.json')
$reqFile = [IO.Path]::Combine($reqDir, 'request.json')
$resFile = [IO.Path]::Combine($reqDir, 'gesture.json')
Write-Utf8NoBom $stateFile "pending`n"
Write-Utf8NoBom $sentinelFile "$PID`n"
Write-Utf8NoBom $snapFile $revRaw

$cards = New-Object System.Collections.Generic.List[object]
function Build-OptionList($opts) {
    $outOpts = New-Object System.Collections.Generic.List[object]
    foreach ($o in @($opts)) {
        if (-not $o) { continue }
        $rl = 0
        if ($o.PSObject.Properties['risk'] -and ([string]$o.risk) -match '^(\d+)/') { $rl = [int]$Matches[1] }
        $eff = if ($o.PSObject.Properties['effort_h'] -and $null -ne $o.effort_h) { "~$($o.effort_h)h" } else { '' }
        $un = if ($o.PSObject.Properties['undo'] -and $o.undo) { [string]$o.undo } else { '' }
        $chips = New-Object System.Collections.Generic.List[string]
        if ($eff) { $chips.Add($eff) }
        if ($rl -gt 0) { $chips.Add("risk $rl/4") }
        if ($un) { $chips.Add($un) }
        if ($o.PSObject.Properties['parity']) {
            if ($o.parity -eq 'diverges') { $chips.Add('diverges') }
            if ($o.parity -in @('same', 'diverges')) { $chips.Add("parity $($o.parity)") }
        }
        foreach ($key in @('leverage', 'confidence', 'complexity')) {
            $prop = $o.PSObject.Properties[$key]
            if ($prop -and [string]$prop.Value -match '^[1-4]/4$') { $chips.Add("$key $($prop.Value)") }
        }
        $deps = $o.PSObject.Properties['deps']
        if ($deps) { foreach ($dep in $deps.Value) { $chips.Add("dependency $dep") } }
        $domProp = $o.PSObject.Properties['dominated_by']
        $domBy = if ($domProp -and $domProp.Value) { @($domProp.Value | ForEach-Object { [string]$_ } | Where-Object { $_ }) } else { @() }
        $outOpts.Add(@{
            id = [string]$o.id
            does = [string]$o.does
            summary = ($chips -join ' · ')
            chips = $chips
            effort = $eff
            risk_level = $rl
            undo = $un
            dominated_by = $domBy
        })
    }
    return ,$outOpts
}

function Get-TomlWhyMap([string]$AreaPath, [string]$RelFile) {
    $res = @{}
    if (-not $RelFile) { return $res }
    try {
        $cand = [IO.Path]::GetFullPath([IO.Path]::Combine($AreaPath, $RelFile))
        if (-not (Test-Path -LiteralPath $cand -PathType Leaf) -or (Test-IsReparse $cand)) { return $res }
        $curId = ''
        foreach ($ln in [IO.File]::ReadAllLines($cand, $Utf8NoBom)) {
            $t = $ln.Trim()
            if ($t -match '^\[(decisions|open)\.([^\]]+)\]$') { $curId = $Matches[2].Trim(); continue }
            if ($t -match '^\[') { $curId = ''; continue }
            if ($curId -and $t -match '^why\s*=\s*"([^"]+)"') { $res[$curId] = $Matches[1] }
        }
    } catch {}
    return $res
}

function Format-CleanVal($v) {
    if ($null -eq $v) { return 'null' }
    if ($v -is [bool]) { return $(if ($v) { 'true' } else { 'false' }) }
    if ($v -is [string] -or $v -is [ValueType]) { return [string]$v }
    if ($v -is [System.Collections.IEnumerable] -and -not ($v -is [PSCustomObject]) -and -not ($v -is [System.Collections.IDictionary])) {
        return (@($v | ForEach-Object { Format-CleanVal $_ }) -join ', ')
    }
    $props = @($v.PSObject.Properties)
    $names = @($props | ForEach-Object { $_.Name })
    if (($names -contains 'min') -and ($names -contains 'max') -and $names.Count -eq 2) { return "$($v.min) – $($v.max)" }
    if (($names -contains 'min') -and $names.Count -eq 1) { return "≥ $($v.min)" }
    if (($names -contains 'max') -and $names.Count -eq 1) { return "≤ $($v.max)" }
    if (($names -contains 'in') -and $names.Count -eq 1) { return (@($v.in | ForEach-Object { Format-CleanVal $_ }) -join ' / ') }
    $parts = @($props | Sort-Object Name | ForEach-Object { "$($_.Name): $(Format-CleanVal $_.Value)" })
    if ($parts.Count -gt 0) { return ($parts -join ', ') }
    return ($v | ConvertTo-Json -Compress)
}

function Get-ClausePairs($m, $relaxedSet) {
    $out = New-Object System.Collections.Generic.List[object]
    if ($null -eq $m) { return ,$out }
    foreach ($p in @($m.PSObject.Properties | Sort-Object Name)) {
        $k = [string]$p.Name
        $isRel = ($null -ne $relaxedSet -and $relaxedSet.Contains($k))
        $out.Add(@{ key = $k; val = (Format-CleanVal $p.Value); relaxed = $isRel })
    }
    return ,$out
}

function Format-ClauseMap($m) {
    $pairs = Get-ClausePairs $m $null
    if ($pairs.Count -eq 0) { return '—' }
    return (@($pairs | ForEach-Object { "$($_.key): $($_.val)" }) -join ', ')
}

function Get-RelaxedCasePreds($coarsened, $witnesses) {
    $byCase = @{}
    foreach ($rw in @($witnesses)) {
        if (-not $rw) { continue }
        $c = if ($rw.PSObject.Properties['case']) { [string]$rw.case } else { '' }
        $pr = if ($rw.PSObject.Properties['predicate']) { [string]$rw.predicate } else { '' }
        if ($c -and $pr) {
            if (-not $byCase.ContainsKey($c)) { $byCase[$c] = New-Object System.Collections.Generic.HashSet[string] }
            [void]$byCase[$c].Add($pr)
        }
    }
    foreach ($cs in @($coarsened)) {
        $s = [string]$cs
        $tail = if ($s.Contains(':')) { $s.Substring($s.IndexOf(':') + 1) } else { $s }
        $sep = if ($tail.Contains('.')) { '.' } elseif ($tail.Contains(':')) { ':' } else { '' }
        if ($sep) {
            $idx = $tail.IndexOf($sep)
            $c = $tail.Substring(0, $idx)
            $pr = $tail.Substring($idx + 1)
            if (-not $byCase.ContainsKey($c)) { $byCase[$c] = New-Object System.Collections.Generic.HashSet[string] }
            [void]$byCase[$c].Add($pr)
        }
    }
    return $byCase
}

function Format-HumanRelaxations($coarsened, $witnesses) {
    $out = New-Object System.Collections.Generic.List[object]
    $covered = New-Object System.Collections.Generic.HashSet[string]
    foreach ($rw in @($witnesses)) {
        if (-not $rw) { continue }
        $c = if ($rw.PSObject.Properties['case']) { [string]$rw.case } else { '' }
        $pr = if ($rw.PSObject.Properties['predicate']) { [string]$rw.predicate } else { '' }
        $knd = if ($rw.PSObject.Properties['kind']) { [string]$rw.kind } else { '' }
        if ($c -and $pr) { [void]$covered.Add("$c.$pr") }
        if ($rw.PSObject.Properties['witness'] -and $rw.witness) {
            $out.Add(@{ title = $(if ($c) { $c } else { 'Relaxed constraint' }); detail = [string]$rw.witness })
            continue
        }
        $lbl = if ($c -and $pr) { "$c · $pr" } elseif ($c) { $c } else { $pr }
        if ($knd -in @('then.widened', 'writes.widened')) {
            $wh = Format-ClauseMap $(if ($rw.PSObject.Properties['when']) { $rw.when } else { $null })
            $adm = Format-CleanVal $(if ($rw.PSObject.Properties['admitted_after']) { $rw.admitted_after } else { $null })
            $out.Add(@{ title = "Widened output  ·  $lbl"; detail = "Admits $pr = $adm   (when $wh)" })
        } elseif ($knd -in @('when.narrowed', 'when.shifted')) {
            $unc = Format-ClauseMap $(if ($rw.PSObject.Properties['uncovered_when']) { $rw.uncovered_when } else { $null })
            $out.Add(@{ title = "Narrowed input  ·  $lbl"; detail = "Drops coverage for $unc" })
        } else {
            $out.Add(@{ title = "Relaxed  ·  $lbl"; detail = ($rw | ConvertTo-Json -Compress) })
        }
    }
    foreach ($cs in @($coarsened)) {
        $s = [string]$cs
        $tail = if ($s.Contains(':')) { $s.Substring($s.IndexOf(':') + 1) } else { $s }
        if (-not $covered.Contains($tail)) {
            $out.Add(@{ title = "Relaxed  ·  $tail"; detail = 'Broader than baseline.' })
        }
    }
    return ,$out
}

function Get-ImpactsList($rawList) {
    $seen = New-Object System.Collections.Generic.HashSet[string]
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($r in @($rawList)) {
        if (-not $r) { continue }
        $s = [string]$r
        $rhs = if ($s.Contains('->')) { $s.Substring($s.IndexOf('->') + 2) } elseif ($s.Contains(':')) { $s.Substring($s.IndexOf(':') + 1) } else { '' }
        $cid = (($rhs -split '#')[0] -split ':')[0].Trim()
        if ($cid -and $seen.Add($cid)) { $out.Add($cid) }
    }
    $out.Sort()
    return ,$out
}

$intentById = @{}
$impactsById = @{}
$whyCache = @{}
$contractPanels = New-Object System.Collections.Generic.List[object]
$execChoices = New-Object System.Collections.Generic.List[object]
$relaxedCount = 0
$removedCount = 0
$impactsSet = New-Object System.Collections.Generic.HashSet[string]
foreach ($c in @($doc.contracts)) {
    if (-not $c) { continue }
    $cid = [string]$c.id
    $cIntent = $(if ($c.PSObject.Properties['intent']) { [string]$c.intent } else { '' })
    $intentById[$cid] = $cIntent
    $bd = if ($c.PSObject.Properties['baseline_delta'] -and $c.baseline_delta) { $c.baseline_delta } else { $null }
    $coarsened = if ($bd -and $bd.PSObject.Properties['coarsened']) { @($bd.coarsened | ForEach-Object { [string]$_ }) } else { @() }
    $rawWits = if ($bd -and $bd.PSObject.Properties['relaxation_witnesses']) { @($bd.relaxation_witnesses) } else { @() }
    $relaxedCount += $coarsened.Count
    $relItems = Format-HumanRelaxations $coarsened $rawWits
    $relaxedByCase = Get-RelaxedCasePreds $coarsened $rawWits

    $caseRows = New-Object System.Collections.Generic.List[object]
    $seenCases = New-Object System.Collections.Generic.HashSet[string]
    if ($bd -and $bd.PSObject.Properties['case_changes']) {
        foreach ($cc in @($bd.case_changes)) {
            if (-not $cc) { continue }
            $knd = [string]$cc.kind
            $ccId = [string]$cc.case
            if ($knd -in @('removed', 'waived', 'deferred')) { $removedCount++ }
            $srcM = if ($cc.PSObject.Properties['after'] -and $cc.after) { $cc.after } elseif ($cc.PSObject.Properties['before'] -and $cc.before) { $cc.before } else { $null }
            $whObj = if ($srcM -and $srcM.PSObject.Properties['when']) { $srcM.when } else { $null }
            $thObj = if ($srcM -and $srcM.PSObject.Properties['then']) { $srcM.then } else { $null }
            $rSet = if ($relaxedByCase.ContainsKey($ccId)) { $relaxedByCase[$ccId] } else { $null }
            [void]$seenCases.Add($ccId)
            $caseRows.Add(@{
                id = $ccId
                badge = $(if ($knd) { $knd.ToUpperInvariant() } else { 'CHANGED' })
                when_text = (Format-ClauseMap $whObj)
                then_text = (Format-ClauseMap $thObj)
                when_pairs = (Get-ClausePairs $whObj $rSet)
                then_pairs = (Get-ClausePairs $thObj $rSet)
            })
        }
    }
    if ($c.PSObject.Properties['active_cases']) {
        foreach ($ac in @($c.active_cases)) {
            if (-not $ac) { continue }
            $acId = [string]$ac.id
            if ($seenCases.Contains($acId)) { continue }
            $whObj = if ($ac.PSObject.Properties['when']) { $ac.when } else { $null }
            $thObj = if ($ac.PSObject.Properties['then']) { $ac.then } else { $null }
            $rSet = if ($relaxedByCase.ContainsKey($acId)) { $relaxedByCase[$acId] } else { $null }
            $stLbl = if ($ac.PSObject.Properties['status'] -and $ac.status) { ([string]$ac.status).ToUpperInvariant() } else { 'ACTIVE' }
            $caseRows.Add(@{
                id = $acId
                badge = $stLbl
                when_text = (Format-ClauseMap $whObj)
                then_text = (Format-ClauseMap $thObj)
                when_pairs = (Get-ClausePairs $whObj $rSet)
                then_pairs = (Get-ClausePairs $thObj $rSet)
            })
        }
    }
    $cImpacts = Get-ImpactsList $(if ($bd -and $bd.PSObject.Properties['boundary_impact']) { $bd.boundary_impact } else { @() })
    $impactsById[$cid] = $cImpacts
    foreach ($bi in $cImpacts) { [void]$impactsSet.Add([string]$bi) }
    $sc = if ($c.PSObject.Properties['scope_summary'] -and $c.scope_summary) { $c.scope_summary } else { $null }
    $hasBase = [bool]($bd -ne $null)
    $ccObj = if ($c.PSObject.Properties['clause_counts'] -and $c.clause_counts) { $c.clause_counts } else { $null }
    $hasCounts = [bool]($ccObj -ne $null -or $c.PSObject.Properties['active_cases'])
    $actCasesN = if ($ccObj -and $ccObj.PSObject.Properties['active_cases']) { [int]$ccObj.active_cases } elseif ($c.PSObject.Properties['active_cases'] -and $c.active_cases) { @($c.active_cases | Where-Object { -not $_.PSObject.Properties['status'] -or $_.status -eq 'active' }).Count } else { 0 }
    $invN = if ($ccObj -and $ccObj.PSObject.Properties['invariants']) { [int]$ccObj.invariants } else { 0 }
    $budN = if ($ccObj -and $ccObj.PSObject.Properties['budgets']) { [int]$ccObj.budgets } else { 0 }
    $frmN = if ($ccObj -and $ccObj.PSObject.Properties['formal']) { [int]$ccObj.formal } else { 0 }
    $chgKind = if ($bd -and $bd.PSObject.Properties['contract_change']) { [string]$bd.contract_change } else { 'snapshot' }
    $addCasesN = if ($hasBase) { if ($chgKind -eq 'added') { $actCasesN } elseif ($bd.PSObject.Properties['case_changes'] -and $bd.case_changes) { @($bd.case_changes | Where-Object { $_ -and [string]$_.kind -eq 'added' }).Count } else { 0 } } else { 0 }
    $contractPanels.Add(@{
        id = $cid
        file = [string]$c.file
        intent = $cIntent
        approval = [string]$c.approval
        change_kind = $chgKind
        has_baseline = $hasBase
        has_clause_counts = $hasCounts
        active_cases_count = $actCasesN
        added_cases_count = $addCasesN
        invariants_count = $invN
        budgets_count = $budN
        formal_count = $frmN
        surface = $(if ($sc -and $sc.PSObject.Properties['surface']) { [string]$sc.surface } else { '' })
        coarsened = $coarsened
        witnesses = @()
        relaxations = $relItems
        impacts = $cImpacts
        cases = $caseRows
        code = $(if ($sc -and $sc.PSObject.Properties['code']) { @($sc.code | ForEach-Object { [string]$_ }) } else { @() })
        reads = $(if ($sc -and $sc.PSObject.Properties['reads']) { @($sc.reads | ForEach-Object { [string]$_ }) } else { @() })
        writes = $(if ($sc -and $sc.PSObject.Properties['writes']) { @($sc.writes | ForEach-Object { [string]$_ }) } else { @() })
    })
}
if ($doc.PSObject.Properties['settled_execution_choices']) {
    foreach ($se in @($doc.settled_execution_choices)) {
        if (-not $se) { continue }
        $ecDoes = if ($se.PSObject.Properties['does'] -and $se.does -and [string]$se.does -ne 'unknown') { [string]$se.does } else { '' }
        $ecEff = if ($se.PSObject.Properties['effort_h'] -and $null -ne $se.effort_h -and [string]$se.effort_h -ne '' -and [string]$se.effort_h -ne 'unknown') { "~$($se.effort_h)h" } else { '' }
        $ecRl = if ($se.PSObject.Properties['risk'] -and ([string]$se.risk) -match '^(\d+)/') { [int]$Matches[1] } else { 0 }
        $ecUndo = if ($se.PSObject.Properties['undo'] -and $se.undo -and [string]$se.undo -ne 'unknown') { [string]$se.undo } else { '' }
        $ecCases = if ($se.PSObject.Properties['cases'] -and $se.cases) { @($se.cases | ForEach-Object { [string]$_ }) } else { @() }
        $execChoices.Add(@{ contract_id = [string]$se.contract_id; card_id = [string]$se.id; pick = [string]$se.pick; ask = [string]$se.ask; why = [string]$se.why; does = $ecDoes; effort = $ecEff; risk_level = $ecRl; undo = $ecUndo; cases = $ecCases })
    }
}
$hiddenCount = 0
foreach ($lim in @($doc.claim_limits)) {
    if (([string]$lim) -match '^(\d+)\s+quiet unchanged contract') { $hiddenCount = [int]$Matches[1] }
}

$apprDecs = @($doc.decisions | Where-Object { $_ -and (-not $_.PSObject.Properties['blocking_phase'] -or $_.blocking_phase -eq 'approval') })
$apprQs = @($doc.questions | Where-Object { $_ -and (-not $_.PSObject.Properties['blocking_phase'] -or $_.blocking_phase -eq 'approval') })
foreach ($d in $apprDecs) {
    $cf = [string]$d.contract
    $cid = [string]$(if ($d.PSObject.Properties['contract_id'] -and $d.contract_id) { $d.contract_id } else { $cf })
    if (-not $whyCache.ContainsKey($cf)) { $whyCache[$cf] = Get-TomlWhyMap $area $cf }
    $wTxt = if ($whyCache[$cf].ContainsKey([string]$d.id)) { [string]$whyCache[$cf][[string]$d.id] } else { '' }
    $cCases = if ($d.PSObject.Properties['cases'] -and $d.cases) { @($d.cases | ForEach-Object { [string]$_ }) } else { @() }
    $cards.Add(@{
        contract_id = $cid
        contract_file = $cf
        contract_intent = $(if ($intentById.ContainsKey($cid)) { $intentById[$cid] } else { '' })
        card_kind = 'decision'
        card_id = [string]$d.id
        ask = [string]$d.ask
        why = $wTxt
        cases = $cCases
        proposed_pick = ''
        recommended_option = $(if ($d.PSObject.Properties['recommendation'] -and $d.recommendation) { [string]$d.recommendation.option } else { '' })
        changed_since_prior = $false
        impacts = $(if ($impactsById.ContainsKey($cid)) { $impactsById[$cid] } else { @() })
        options = (Build-OptionList $d.options)
    })
}
if ($doc.PSObject.Properties['proposed_choices']) {
    foreach ($p in @($doc.proposed_choices)) {
        if (-not $p) { continue }
        $cf = [string]$p.contract
        $cid = [string]$p.contract_id
        if (-not $whyCache.ContainsKey($cf)) { $whyCache[$cf] = Get-TomlWhyMap $area $cf }
        $wTxt = if ($whyCache[$cf].ContainsKey([string]$p.id)) { [string]$whyCache[$cf][[string]$p.id] } else { '' }
        $cCases = if ($p.PSObject.Properties['cases'] -and $p.cases) { @($p.cases | ForEach-Object { [string]$_ }) } else { @() }
        $cards.Add(@{
            contract_id = $cid
            contract_file = $cf
            contract_intent = $(if ($intentById.ContainsKey($cid)) { $intentById[$cid] } else { '' })
            card_kind = 'proposed_choice'
            card_id = [string]$p.id
            ask = [string]$p.ask
            why = $wTxt
            cases = $cCases
            proposed_pick = [string]$p.proposed_pick
            recommended_option = $(if ($p.PSObject.Properties['recommendation'] -and $p.recommendation) { [string]$p.recommendation.option } else { '' })
            changed_since_prior = $false
            impacts = $(if ($impactsById.ContainsKey($cid)) { $impactsById[$cid] } else { @() })
            options = (Build-OptionList $p.options)
        })
    }
}
foreach ($q in $apprQs) {
    $cf = [string]$q.contract
    $cid = [string]$(if ($q.PSObject.Properties['contract_id'] -and $q.contract_id) { $q.contract_id } else { $cf })
    if (-not $whyCache.ContainsKey($cf)) { $whyCache[$cf] = Get-TomlWhyMap $area $cf }
    $wTxt = if ($whyCache[$cf].ContainsKey([string]$q.id)) { [string]$whyCache[$cf][[string]$q.id] } else { '' }
    $cards.Add(@{
        contract_id = $cid
        contract_file = $cf
        contract_intent = $(if ($intentById.ContainsKey($cid)) { $intentById[$cid] } else { '' })
        card_kind = 'question'
        card_id = [string]$q.id
        ask = [string]$q.ask
        why = $wTxt
        cases = @()
        proposed_pick = ''
        recommended_option = ''
        changed_since_prior = $false
        impacts = @()
        options = @()
    })
}

$targs = if ($snap -and $snap.PSObject.Properties['targets']) { @($snap.targets) } else { @() }
$targetItems = @($targs | ForEach-Object { @{ path = [string]$_.path; behavior_digest = [string]$_.digest; assurance_digest = [string]$_.assurance_digest } })
$canSeal = [bool]($revRef -and $apprDecs.Count -eq 0 -and $apprQs.Count -eq 0 -and @($doc.blocking_reasons).Count -eq 0)
$suggOwner = if ($cfg.owner) { '' } else { Get-HostSuggestedOwner }

$wsMeta = Get-WorkspaceIdentity $area
$bannerImpacts = @($impactsSet)
$kwarn = [bool]($relaxedCount -gt 0 -or $removedCount -gt 0 -or $bannerImpacts.Count -gt 0)

$reqObj = @{
    schema = 'drift.ui-request/1'
    request_id = $attemptId
    area_name = (Split-Path -Leaf $area)
    project_name = [string]$wsMeta.project_name
    worktree_name = [string]$wsMeta.worktree_name
    is_linked_worktree = [bool]$wsMeta.is_linked_worktree
    git_branch = [string]$wsMeta.git_branch
    workspace_path = [string]$wsMeta.workspace_path
    edition = $edition
    theme = $cfg.theme
    owner = $cfg.owner
    needs_owner_enrollment = (-not [bool]$cfg.owner)
    suggested_owner = $suggOwner
    policy_approvers = @()
    review_ref = $revRef
    quiet_arm_ms = $cfg.quiet_arm_ms
    timeout_s = $cfg.timeout_s
    sentinel_path = $sentinelFile
    can_seal_directly = $canSeal
    kernel_banner = "$($targs.Count) target(s)"
    kernel_warning = $kwarn
    targets_count = $targs.Count
    relaxed_count = $relaxedCount
    removed_count = $removedCount
    hidden_count = $hiddenCount
    banner_impacts = $bannerImpacts
    cases_tab = ($doc.contracts | ConvertTo-Json -Depth 6)
    perimeter_tab = 'Windows native session'
    targets_tab = "review_ref: $revRef"
    contract_panels = $contractPanels
    exec_choices = $execChoices
    target_items = $targetItems
    claim_limits = @($doc.claim_limits)
    cards = $cards
}
Write-Utf8NoBom $reqFile ($reqObj | ConvertTo-Json -Depth 10 -Compress)

try {
    $qReq = "`"$reqFile`""
    $qRes = "`"$resFile`""
    $proc = Start-Process -FilePath $runnerExe -ArgumentList @($qReq, $qRes) -WorkingDirectory $area -PassThru
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $resFile -PathType Leaf)) {
        Invoke-Fallback 'renderer_failed'
    }
} finally {
    Remove-Item -LiteralPath $sentinelFile -Force -ErrorAction SilentlyContinue
}

$gest = ([IO.File]::ReadAllText($resFile, $Utf8NoBom)) | ConvertFrom-Json
$act = [string]$gest.action
if ($act -eq 'timeout') { Invoke-Fallback 'idle_timeout' }
if ($act -eq 'use_terminal_once') { Invoke-Fallback 'user_used_terminal_once' }
if ($act -eq 'disable_ui') {
    Save-UiConfigFields @{ mode = 'off' } | Out-Null
    Invoke-Fallback 'user_switched_to_terminal'
}
if ($act -eq 'cancel') {
    Write-Utf8NoBom $stateFile "cancelled`n"
    Write-Output (@{ approval_writes = 0; request_id = $attemptId; schema = 'drift.ui-result/1'; status = 'cancelled' } | ConvertTo-Json -Compress)
    exit 1
}
if ($act -eq 'amend') {
    Write-Output (@{
        approval_writes = 0
        card_diff = @()
        note = [string]$gest.note
        request_id = $attemptId
        schema = 'drift.ui-result/1'
        selections = @($gest.selections)
        status = 'amend_requested'
    } | ConvertTo-Json -Compress)
    exit 1
}
if ($act -ne 'approve') { Stop-Broker "unknown gesture action: $act" 2 }
if (-not $revRef -or [string]$gest.confirmed_review_ref -ne $revRef) { Stop-Broker 'confirmed_review_ref mismatch' 2 }

$effOwner = ([string]$gest.confirmed_owner).Trim()
if (-not $effOwner) { Stop-Broker 'approve gesture requires non-empty owner' 2 }

$targetPaths = @($targs | ForEach-Object { [string]$_.path } | Where-Object { $_ })
$areaHash = ([BitConverter]::ToString(([Security.Cryptography.SHA256]::Create()).ComputeHash($Utf8NoBom.GetBytes($area)))).Replace('-', '').Substring(0, 16)
$areaMtx = New-Object System.Threading.Mutex($false, "Local\DriftUi_AreaLock_$areaHash")
$areaLocked = $false
try {
    try { $areaLocked = $areaMtx.WaitOne([TimeSpan]::FromSeconds(15)) } catch [System.Threading.AbandonedMutexException] { $areaLocked = $true }
    $curState = if (Test-Path -LiteralPath $stateFile -PathType Leaf) { ([IO.File]::ReadAllText($stateFile, $Utf8NoBom)).Trim() } else { '' }
    if ($curState -ne 'pending') { Stop-Broker "request $attemptId is '$curState', refusing commit" 2 }
    Write-Utf8NoBom $stateFile "committing`n"

    $preStates = Get-TargetStates $driftExe $area $targetPaths
    Push-Location -LiteralPath $area
    try {
        $apprArgs = @('approve', '--reviewed', $snapFile, '--expect-review', $revRef, '--by', $effOwner)
        if ($cfg.ssh_sign_key) { $apprArgs += @('--ssh-sign', $cfg.ssh_sign_key) }
        $apprOut = & $driftExe @apprArgs 2>&1
        $apprCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $postStates = Get-TargetStates $driftExe $area $targetPaths
    $allCurrent = ($targetPaths.Count -gt 0) -and (@($targetPaths | Where-Object { $postStates[$_] -ne 'current' }).Count -eq 0)
    $newlyApproved = @($targetPaths | Where-Object { $postStates[$_] -eq 'current' -and $preStates[$_] -ne 'current' }).Count
    $totalCurrent = @($targetPaths | Where-Object { $postStates[$_] -eq 'current' }).Count
    $sigOk = (-not $cfg.ssh_sign_key) -or ((Test-Path -LiteralPath "$snapFile.sig" -PathType Leaf) -and $apprCode -eq 0)
    $errText = ($apprOut -join "`n").Trim()

    if ($allCurrent) {
        if (-not $cfg.owner -and $effOwner) { Save-UiConfigFields @{ owner = $effOwner } | Out-Null }
        $writesCnt = if ($newlyApproved -gt 0) { $newlyApproved } else { $totalCurrent }
        if ($sigOk -and $apprCode -eq 0) {
            Write-Utf8NoBom $stateFile "committed`n"
            Write-Output (@{ approval_writes = $writesCnt; owner = $effOwner; request_id = $attemptId; review_ref = $revRef; schema = 'drift.ui-result/1'; status = 'approved'; targets_state = $postStates } | ConvertTo-Json -Compress)
            exit 0
        }
        Write-Utf8NoBom $stateFile "committed_unsigned`n"
        Write-Output (@{ approval_writes = $writesCnt; error = $errText; owner = $effOwner; request_id = $attemptId; review_ref = $revRef; schema = 'drift.ui-result/1'; status = 'approved_unsigned'; targets_state = $postStates } | ConvertTo-Json -Compress)
        exit 1
    }
    if ($newlyApproved -gt 0 -and -not $allCurrent) {
        Write-Utf8NoBom $stateFile "partial`n"
        Write-Output (@{ approval_writes = $newlyApproved; error = $errText; owner = $effOwner; request_id = $attemptId; review_ref = $revRef; schema = 'drift.ui-result/1'; status = 'partial'; targets_state = $postStates } | ConvertTo-Json -Compress)
        exit 2
    }
    Write-Utf8NoBom $stateFile "rejected`n"
    Write-Output (@{ approval_writes = 0; error = $errText; request_id = $attemptId; review_ref = $revRef; schema = 'drift.ui-result/1'; status = 'rejected'; targets_state = $postStates } | ConvertTo-Json -Compress)
    exit $(if ($apprCode -in @(1, 2)) { $apprCode } else { 1 })
} finally {
    if ($areaLocked) { try { $areaMtx.ReleaseMutex() } catch {} }
    $areaMtx.Dispose()
}
