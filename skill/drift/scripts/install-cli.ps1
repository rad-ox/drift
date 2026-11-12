<#
.SYNOPSIS
Downloads, SHA-256-verifies, and installs the matching DRIFT Free release
package on 64-bit Windows when the skill was installed standalone (e.g. via
`npx skills add rad-ox/drift`).
#>
[CmdletBinding()]
param(
    [string]$Prefix,
    [string]$MavenRepo,
    [switch]$Hooks,
    [switch]$NoHooks,
    [switch]$UpdateCheck,
    [switch]$NoUpdateCheck,
    [switch]$NoMaven,
    [switch]$NoPath,
    [switch]$DryRun,
    [ValidateSet('', 'en', 'it')]
    [string]$Lang = '',
    [switch]$Force,
    [switch]$Help
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

if ($Help) {
    Write-Host @'
Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-cli.ps1 [-Force] [install.ps1 options...]

Downloads, verifies (SHA256SUMS), and installs the matching DRIFT release binary
and bridges for 64-bit Windows from GitHub Releases. Additional options
(-Prefix DIR, -NoMaven, -Hooks, -DryRun, ...) are forwarded to install.ps1 with -NoSkill.
'@
    exit 0
}

$defaultVersion = '0.6.0'
$repo = if ($env:DRIFT_GITHUB_REPO) { $env:DRIFT_GITHUB_REPO } else { 'rad-ox/drift' }
$localData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [IO.Path]::Combine([string]$HOME, 'AppData', 'Local') }
$targetPrefix = if ($Prefix) { [IO.Path]::GetFullPath($Prefix) } else { [IO.Path]::Combine($localData, 'Programs', 'drift') }
$targetExe = [IO.Path]::Combine($targetPrefix, 'bin', 'drift.exe')

if (-not $Force) {
    if ($Prefix) {
        if (Test-Path -LiteralPath $targetExe -PathType Leaf) {
            if ($env:DRIFT_INSTALL_TEST -eq '1') { Write-Host "drift $defaultVersion" } else { & $targetExe version }
            exit 0
        }
    } else {
        $existing = Get-Command drift.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($existing) {
            if ($env:DRIFT_INSTALL_TEST -eq '1') { Write-Host "drift $defaultVersion" } else { & $existing.Source version }
            exit 0
        }
        if (Test-Path -LiteralPath $targetExe -PathType Leaf) {
            if ($env:DRIFT_INSTALL_TEST -eq '1') { Write-Host "drift $defaultVersion" } else { & $targetExe version }
            exit 0
        }
    }
}

$ver = if ($env:DRIFT_VERSION) { $env:DRIFT_VERSION.Trim() } else { '' }
if (-not $ver) {
    foreach ($rel in @('..\..\..\VERSION', '..\..\VERSION')) {
        $cand = [IO.Path]::Combine($PSScriptRoot, $rel)
        if (Test-Path -LiteralPath $cand -PathType Leaf) {
            $ver = (Get-Content -LiteralPath $cand -TotalCount 1).Trim()
            break
        }
    }
    if (-not $ver) { $ver = $defaultVersion }
}

$pkg = "drift-$ver-windows-x64"
$base = if ($env:DRIFT_RELEASE_BASE_URL) { $env:DRIFT_RELEASE_BASE_URL.TrimEnd('/') } else { "https://github.com/$repo/releases/download/v$ver" }
$tmpDir = [IO.Path]::Combine([IO.Path]::GetTempPath(), "drift-cli-dl-$([Guid]::NewGuid().ToString('N'))")
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

try {
    $zipPath = [IO.Path]::Combine($tmpDir, "$pkg.zip")
    $sumsPath = [IO.Path]::Combine($tmpDir, 'SHA256SUMS')
    if ($base.StartsWith('file://', [StringComparison]::OrdinalIgnoreCase)) {
        $srcDir = $base.Substring(7)
        Copy-Item -LiteralPath ([IO.Path]::Combine($srcDir, "$pkg.zip")) -Destination $zipPath -Force
        Copy-Item -LiteralPath ([IO.Path]::Combine($srcDir, 'SHA256SUMS')) -Destination $sumsPath -Force
    } elseif (Test-Path -LiteralPath $base -PathType Container) {
        Copy-Item -LiteralPath ([IO.Path]::Combine($base, "$pkg.zip")) -Destination $zipPath -Force
        Copy-Item -LiteralPath ([IO.Path]::Combine($base, 'SHA256SUMS')) -Destination $sumsPath -Force
    } else {
        Invoke-WebRequest -Uri "$base/$pkg.zip" -OutFile $zipPath -UseBasicParsing
        Invoke-WebRequest -Uri "$base/SHA256SUMS" -OutFile $sumsPath -UseBasicParsing
    }

    $matchLine = Select-String -LiteralPath $sumsPath -Pattern "  $([regex]::Escape($pkg))\.zip$" | Select-Object -First 1
    if (-not $matchLine) {
        throw "drift: $pkg.zip not found in SHA256SUMS"
    }
    $expected = ($matchLine.Line -split '\s+')[0].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected -ne $actual) {
        throw "drift: downloaded archive $pkg.zip failed SHA256SUMS verification"
    }

    Expand-Archive -LiteralPath $zipPath -DestinationPath $tmpDir -Force
    $fwd = @{ NoSkill = $true }
    foreach ($k in @('Prefix', 'MavenRepo', 'Hooks', 'NoHooks', 'UpdateCheck', 'NoUpdateCheck', 'NoMaven', 'NoPath', 'DryRun', 'Lang')) {
        if ($PSBoundParameters.ContainsKey($k)) {
            $fwd[$k] = $PSBoundParameters[$k]
        }
    }
    & ([IO.Path]::Combine($tmpDir, $pkg, 'install.ps1')) @fwd
} finally {
    if (Test-Path -LiteralPath $tmpDir) {
        Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
