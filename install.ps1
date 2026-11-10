<#
.SYNOPSIS
Installs DRIFT for the current user on Windows 10 or 11 (x64).

.DESCRIPTION
Copies drift.exe, the agent skill, the JUnit bridge and the Maven plugin to
per-user locations,
adds drift to the user PATH and lists it in Settings > Apps, so that it can be
removed from there or with -Uninstall. No administrator rights, no network.
Run it again to update. Usually started through install.cmd.

.EXAMPLE
.\install.cmd

.EXAMPLE
.\install.cmd -Uninstall
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '', Justification = 'Interactive installer output')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseShouldProcessForStateChangingFunctions', '', Justification = '-DryRun covers every change')]
[CmdletBinding()]
param(
    [string]$Prefix,
    [string]$SkillsDir,
    [string]$HooksDir,
    [string]$MavenRepo,
    [switch]$Hooks,
    [switch]$NoHooks,
    [switch]$UpdateCheck,
    [switch]$NoUpdateCheck,
    [switch]$NoSkill,
    [switch]$NoMaven,
    [switch]$NoPath,
    [switch]$DryRun,
    [switch]$Uninstall,
    [ValidateSet('', 'en', 'it')]
    [string]$Lang = '',
    [switch]$Help
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Windows only; DRIFT_INSTALL_TEST=1 lets the repository test the file logic
# with PowerShell on Linux, skipping registry, PATH and running drift.exe.
$onWindows = $true
if ($PSVersionTable.PSEdition -eq 'Core') {
    $onWindows = [bool](Get-Variable -Name IsWindows -ValueOnly -ErrorAction SilentlyContinue)
}
$testMode = (-not $onWindows) -and ($env:DRIFT_INSTALL_TEST -eq '1')

if (-not $Lang) { $Lang = [string]$env:DRIFT_LANG }
if ($Lang -notin @('en', 'it')) {
    $Lang = 'en'
    foreach ($c in @((Get-UICulture), (Get-Culture))) {
        if ($c.TwoLetterISOLanguageName -eq 'it') { $Lang = 'it' }
    }
}
$color = -not $env:NO_COLOR

function T([string]$En, [string]$It) { if ($Lang -eq 'it') { $It } else { $En } }

function Write-Mark([string]$Mark, [string]$Color, [string]$Text) {
    if ($color) {
        Write-Host "  $Mark " -ForegroundColor $Color -NoNewline
        Write-Host $Text
    } else {
        Write-Host "  $Mark $Text"
    }
}
function Ok([string]$En, [string]$It) { Write-Mark -Mark 'OK' -Color 'Green' -Text (T $En $It) }
function Note([string]$En, [string]$It) { Write-Mark -Mark ' !' -Color 'Yellow' -Text (T $En $It) }
function Stop-Install([string]$En, [string]$It) { throw [InvalidOperationException]::new((T $En $It)) }

function Invoke-Step([string]$What, [scriptblock]$Action) {
    if ($DryRun) {
        if ($color) { Write-Host "    $What" -ForegroundColor DarkGray } else { Write-Host "    $What" }
    } else {
        & $Action
    }
}

function Join([string[]]$Parts) { [IO.Path]::Combine($Parts) }

function Show-Path([string]$Path) {
    $h = [string]$HOME
    if ($h -and $Path.StartsWith($h, [StringComparison]::OrdinalIgnoreCase)) {
        if ($onWindows) { return '%USERPROFILE%' + $Path.Substring($h.Length) }
        return '~' + $Path.Substring($h.Length)
    }
    return $Path
}

# Deletes a file or directory; a link is removed without touching its target,
# and a path that does not end as expected is refused.
function Remove-Safely([string]$Path, [string]$Suffix) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $sep = [IO.Path]::DirectorySeparatorChar
    if (-not $full.EndsWith($Suffix.Replace('\', $sep).Replace('/', $sep), [StringComparison]::OrdinalIgnoreCase) -or
        $full -eq [IO.Path]::GetFullPath([string]$HOME).TrimEnd('\', '/')) {
        Stop-Install "Refusing to remove $Path`: unexpected path" "Rimozione di $Path rifiutata: percorso inatteso"
    }
    if (-not (Test-Path -LiteralPath $full)) { return }
    Invoke-Step "remove $full" {
        $item = Get-Item -LiteralPath $full -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            $item.Delete()
        } else {
            Remove-Item -LiteralPath $full -Recurse -Force
        }
    }
}

function Test-Skill([string]$Dir) {
    $f = Join @($Dir, 'SKILL.md')
    (Test-Path -LiteralPath $f) -and [bool](Select-String -LiteralPath $f -Pattern '^name: (drift|drift-recall)$' -Quiet)
}

function Get-UserPath {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment')
    if (-not $key) { return '' }
    try {
        return [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    } finally { $key.Close() }
}

# Writes the user PATH keeping %VARIABLES% unexpanded, then tells running
# programs (Explorer, new terminals) that the environment changed.
function Set-UserPath([string]$Value) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
    try {
        if ($Value) {
            $key.SetValue('Path', $Value, [Microsoft.Win32.RegistryValueKind]::ExpandString)
        } else {
            $key.DeleteValue('Path', $false)
        }
    } finally { $key.Close() }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DriftInstallerNative {
    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern IntPtr SendMessageTimeout(
        IntPtr hWnd, uint msg, IntPtr wParam, string lParam,
        uint flags, uint timeout, out IntPtr result);
}
'@
    $result = [IntPtr]::Zero
    $sent = [DriftInstallerNative]::SendMessageTimeout(
        [IntPtr]0xffff, 0x001A, [IntPtr]::Zero, 'Environment', 0x0002, 5000, [ref]$result)
    if ($sent -eq [IntPtr]::Zero) {
        throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())
    }
}

function Test-SameDir([string]$A, [string]$B) {
    $x = [Environment]::ExpandEnvironmentVariables($A).Trim().TrimEnd('\')
    $y = [Environment]::ExpandEnvironmentVariables($B).Trim().TrimEnd('\')
    return $x -ieq $y
}

function Test-FromExplorer {
    if (-not $onWindows) { return $false }
    try {
        $id = $PID
        for ($i = 0; $i -lt 2; $i++) {
            $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction Stop
            if (-not $p) { return $false }
            $id = $p.ParentProcessId
            $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction Stop
            if ($parent -and $parent.Name -ieq 'explorer.exe') { return $true }
        }
    } catch { return $false }
    return $false
}

function Get-NativeText([string]$Command, [string[]]$Arguments) {
    $cmd = Get-Command $Command -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { return $null }
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        return ((& $cmd.Source @Arguments 2>&1) | ForEach-Object { "$_" }) -join "`n"
    } catch {
        return $null
    } finally { $ErrorActionPreference = $eap }
}

function Show-Usage {
    if ($Lang -eq 'it') {
        Write-Host @'
Uso: install.cmd [opzioni]

Installa DRIFT per l'utente corrente. Rieseguilo per aggiornare; non servono
diritti di amministratore né accesso alla rete.

Opzioni:
  -Prefix DIR       cartella di installazione per drift.exe, guide, bridge e
                    schemi (predefinita: %LOCALAPPDATA%\Programs\drift)
  -SkillsDir DIR    cartella delle skill dell'agente
                    (predefinita: %USERPROFILE%\.copilot\skills e %USERPROFILE%\.agents\skills se presente)
  -NoSkill          non installa la skill dell'agente
  -Hooks            installa gli hook automatici per gli agenti rilevati
                    (pi, copilot, claude, codex, cursor, gemini)
  -NoHooks          non installa gli hook automatici
  -UpdateCheck      installa anche il controllo opzionale delle release GitHub
  -NoUpdateCheck    omette o rimuove solo il controllo delle release
  -HooksDir DIR     installa l'hook automatico in DIR\drift.json
  -MavenRepo DIR    repository Maven locale (predefinito: quello di
                    .m2\settings.xml, altrimenti %USERPROFILE%\.m2\repository)
  -NoMaven          non installa il bridge JUnit e il plugin Maven
  -NoPath           non modifica il PATH dell'utente
  -DryRun           mostra cosa cambierebbe, senza cambiare nulla
  -Uninstall        rimuove quanto installato (anche da Impostazioni > App)
  -Lang en|it       lingua dei messaggi (predefinita: quella di Windows)
  -Help             mostra questo aiuto
'@
    } else {
        Write-Host @'
Usage: install.cmd [options]

Installs DRIFT for the current user. Run it again to update; it needs no
administrator rights and no network access.

Options:
  -Prefix DIR       install directory for drift.exe, guides, bridges and
                    schemas (default: %LOCALAPPDATA%\Programs\drift)
  -SkillsDir DIR    agent skills directory
                    (default: %USERPROFILE%\.copilot\skills and %USERPROFILE%\.agents\skills when present)
  -NoSkill          do not install the agent skill
  -Hooks            install automatic hooks for detected agents
                    (pi, copilot, claude, codex, cursor, gemini)
  -NoHooks          do not install automatic hooks
  -UpdateCheck      also install optional GitHub release checks
  -NoUpdateCheck    omit or remove only the release-check component
  -HooksDir DIR     install the automatic hook into DIR\drift.json
  -MavenRepo DIR    local Maven repository (default: the one in
                    .m2\settings.xml, else %USERPROFILE%\.m2\repository)
  -NoMaven          do not install the JUnit bridge and the Maven plugin
  -NoPath           do not change the user PATH
  -DryRun           show what would change, change nothing
  -Uninstall        remove what was installed (also from Settings > Apps)
  -Lang en|it       language of messages (default: the Windows language)
  -Help             show this help
'@
    }
}

$arpKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\drift'
$here = $PSScriptRoot
$code = 0
$pause = $false

try {
    if ($Help) { Show-Usage; exit 0 }
    if (-not $Uninstall -and $UpdateCheck -and ($NoUpdateCheck -or $NoHooks)) {
        Stop-Install 'Conflicting -UpdateCheck and -NoUpdateCheck/-NoHooks options.' `
            'Opzioni -UpdateCheck e -NoUpdateCheck/-NoHooks in conflitto.'
    }
    $pause = Test-FromExplorer
    if (-not $onWindows -and -not $testMode) {
        Stop-Install 'This installer is for Windows; on Linux use install.sh.' `
            "Questo installer è per Windows; su Linux usa install.sh."
    }

    $localData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join @([string]$HOME, 'AppData', 'Local') }
    $prefixSet = [bool]$Prefix
    if (-not $Prefix) { $Prefix = Join @($localData, 'Programs', 'drift') }
    $Prefix = [IO.Path]::GetFullPath($Prefix)
    # The installed copy of this script lives in the install directory.
    if (-not $prefixSet -and (Test-Path -LiteralPath (Join @($here, 'manifest.txt')))) { $Prefix = $here }
    $skillsSet = [bool]$SkillsDir
    if (-not $SkillsDir) { $SkillsDir = Join @([string]$HOME, '.copilot', 'skills') }
    $withHooks = [bool]$Hooks -or [bool]$HooksDir -or [bool]$UpdateCheck
    $hooksSet = [bool]$Hooks -or [bool]$NoHooks -or [bool]$HooksDir -or [bool]$UpdateCheck
    if ($NoHooks) { $withHooks = $false }
    $bin = Join @($Prefix, 'bin')
    $exe = Join @($bin, 'drift.exe')
    $manifest = Join @($Prefix, 'manifest.txt')

    # ------------------------------------------------------------ uninstall
    if ($Uninstall) {
        Write-Host ('DRIFT ' + (T 'uninstall' 'disinstallazione'))
        if ($DryRun) { Note 'Dry run: nothing changes.' 'Prova: non cambia nulla.' }
        if (-not (Test-Path -LiteralPath $manifest)) {
            Stop-Install "Nothing to uninstall: no manifest at $(Show-Path $manifest). Installed with -Prefix? Pass the same -Prefix." `
                "Niente da disinstallare: manca il manifest $(Show-Path $manifest). Installato con -Prefix? Ripeti lo stesso -Prefix."
        }
        Set-Location -LiteralPath ([IO.Path]::GetTempPath())
        foreach ($line in Get-Content -LiteralPath $manifest) {
            $kind, $path = $line -split "`t", 2
            if (-not $path) { continue }
            switch ($kind) {
                'skill' {
                    if (Test-Skill $path) {
                        $sLeaf = Split-Path -Leaf $path
                        if ($sLeaf -in @('drift', 'drift-recall')) {
                            Remove-Safely $path $sLeaf
                        }
                        foreach ($up in @((Split-Path $path), (Split-Path (Split-Path $path)))) {
                            if (-not $DryRun -and $up -and (Test-Path -LiteralPath $up -PathType Container) -and
                                -not (Get-ChildItem -LiteralPath $up -Force | Select-Object -First 1)) {
                                Remove-Item -LiteralPath $up -Force
                            }
                        }
                        Ok "removed $(Show-Path $path)" "rimossa $(Show-Path $path)"
                    }
                }
                'hook' {
                    if (Test-Path -LiteralPath $path -PathType Leaf) {
                        $leaf = Split-Path -Leaf $path
                        if ($leaf -notin @('drift.json', 'drift.ts', 'hooks.json', 'settings.json')) {
                            Stop-Install "Refusing to remove unexpected hook file $path" "Rimozione del file hook inatteso $path rifiutata"
                        }
                        Remove-Safely $path $leaf
                        foreach ($up in @((Split-Path $path), (Split-Path (Split-Path $path)), (Split-Path (Split-Path (Split-Path $path))))) {
                            if (-not $DryRun -and $up -and (Test-Path -LiteralPath $up -PathType Container) -and
                                -not (Get-ChildItem -LiteralPath $up -Force | Select-Object -First 1)) {
                                Remove-Item -LiteralPath $up -Force
                            }
                        }
                        Ok "removed $(Show-Path $path)" "rimosso $(Show-Path $path)"
                    }
                }
                'maven' {
                    if (Test-Path -LiteralPath $path -PathType Container) {
                        # Older manifests tracked the version directory. Remove
                        # only DRIFT's files, preserving other Maven metadata.
                        $v = Split-Path -Leaf $path
                        foreach ($ext in @('jar', 'pom')) {
                            $file = Join @($path, "drift-junit-$v.$ext")
                            if (Test-Path -LiteralPath $file -PathType Leaf) {
                                Remove-Safely $file (Join @('io', 'github', 'rad-ox', 'drift-junit', $v, (Split-Path -Leaf $file)))
                            }
                        }
                        $parents = @($path, (Split-Path $path), (Split-Path (Split-Path $path)), (Split-Path (Split-Path (Split-Path $path))), (Split-Path (Split-Path (Split-Path (Split-Path $path)))))
                        foreach ($up in $parents) {
                            if (-not $DryRun -and (Test-Path -LiteralPath $up -PathType Container) -and
                                -not (Get-ChildItem -LiteralPath $up -Force | Select-Object -First 1)) {
                                Remove-Item -LiteralPath $up -Force
                            }
                        }
                        Ok "removed DRIFT artifacts in $(Show-Path $path)" "rimossi gli artefatti DRIFT in $(Show-Path $path)"
                    } elseif (Test-Path -LiteralPath $path -PathType Leaf) {
                        $v = Split-Path -Leaf (Split-Path -Parent $path)
                        $a = Split-Path -Leaf (Split-Path -Parent (Split-Path -Parent $path))
                        $leaf = Split-Path -Leaf $path
                        if ($a -notin @('drift-junit', 'drift-maven-plugin') -or $leaf -notin @("$a-$v.jar", "$a-$v.pom")) {
                            Stop-Install "Refusing to remove unexpected Maven artifact $path" "Rimozione dell'artefatto Maven inatteso $path rifiutata"
                        }
                        Remove-Safely $path (Join @('io', 'github', 'rad-ox', $a, $v, $leaf))
                        $p1 = Split-Path $path; $p2 = Split-Path $p1; $p3 = Split-Path $p2; $p4 = Split-Path $p3; $p5 = Split-Path $p4
                        foreach ($up in @($p1, $p2, $p3, $p4, $p5)) {
                            if (-not $DryRun -and (Test-Path -LiteralPath $up -PathType Container) -and
                                -not (Get-ChildItem -LiteralPath $up -Force | Select-Object -First 1)) {
                                Remove-Item -LiteralPath $up -Force
                            }
                        }
                        Ok "removed $(Show-Path $path)" "rimosso $(Show-Path $path)"
                    }
                }
                'path' {
                    if ($onWindows -and -not $NoPath -and (Test-SameDir $path $bin)) {
                        $userPath = Get-UserPath
                        $kept = @($userPath -split ';' | Where-Object { $_ -and -not (Test-SameDir $_ $bin) })
                        Invoke-Step "remove $bin from the user PATH" { Set-UserPath ($kept -join ';') }
                        Ok 'removed drift from the user PATH' 'rimosso drift dal PATH utente'
                    }
                }
            }
        }
        if ($onWindows -and (Test-Path $arpKey)) {
            Invoke-Step "remove $arpKey" { Remove-Item -Path $arpKey -Recurse -Force }
        }
        try {
            Remove-Safely $Prefix 'drift'
            Ok "removed $(Show-Path $Prefix)" "rimosso $(Show-Path $Prefix)"
        } catch {
            Note "$(Show-Path $Prefix) is in use; delete it after closing programs that use it" `
                "$(Show-Path $Prefix) è in uso; eliminala dopo aver chiuso i programmi che la usano"
        }
        Write-Host (T 'DRIFT is uninstalled. Your contracts and projects are untouched.' `
                'DRIFT è disinstallato. Contratti e progetti non sono stati toccati.')
        exit 0
    }

    # -------------------------------------------------------------- install
    $pkgExe = Join @($here, 'bin', 'drift.exe')
    if (-not (Test-Path -LiteralPath $pkgExe) -or (Test-SameDir $here $Prefix)) {
        Stop-Install 'Run the installer from the extracted release package (bin\drift.exe is missing here).' `
            "Esegui l'installer dal pacchetto estratto (qui manca bin\drift.exe)."
    }
    $version = (Get-Content -LiteralPath (Join @($here, 'VERSION')) -TotalCount 1).Trim()
    if ($onWindows -and -not [Environment]::Is64BitOperatingSystem) {
        Stop-Install 'This package is for 64-bit Windows.' 'Questo pacchetto è per Windows a 64 bit.'
    }
    $sumsFile = Join @($here, 'SHA256SUMS')
    $sourceHashes = @{}
    if ((Test-Path -LiteralPath $sumsFile) -and (Test-Path -LiteralPath (Join @($here, 'skill')))) {
        foreach ($line in Get-Content -LiteralPath $sumsFile) {
            if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+)$') {
                $targetPath = Join (@($here) + ($Matches[2] -split '/'))
                $wantHash = $Matches[1].ToLowerInvariant()
                if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
                    Stop-Install 'Package integrity check failed (SHA256SUMS); re-extract or download the archive again.' `
                        "Verifica di integrità del pacchetto fallita (SHA256SUMS); estrai o scarica di nuovo l'archivio."
                }
                $gotHash = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($gotHash -ne $wantHash) {
                    Stop-Install 'Package integrity check failed (SHA256SUMS); re-extract or download the archive again.' `
                        "Verifica di integrità del pacchetto fallita (SHA256SUMS); estrai o scarica di nuovo l'archivio."
                }
                $sourceHashes[$targetPath] = $gotHash
            }
        }
    }

    if (-not $MavenRepo) {
        $MavenRepo = Join @([string]$HOME, '.m2', 'repository')
        $settings = Join @([string]$HOME, '.m2', 'settings.xml')
        if (Test-Path -LiteralPath $settings) {
            try {
                $xml = New-Object Xml.XmlDocument
                $xml.Load($settings)
                $node = $xml.SelectSingleNode("/*[local-name()='settings']/*[local-name()='localRepository']")
                if ($node -and $node.InnerText.Trim()) {
                    $v = $node.InnerText.Trim().Replace('${user.home}', [string]$HOME)
                    $MavenRepo = [regex]::Replace($v, '\$\{env\.([^}]+)\}', { param($m) [Environment]::GetEnvironmentVariable($m.Groups[1].Value) })
                }
            } catch {
                Note "cannot read $(Show-Path $settings); using $(Show-Path $MavenRepo)" `
                    "impossibile leggere $(Show-Path $settings); uso $(Show-Path $MavenRepo)"
            }
        }
    }
    $mavenDir = Join @($MavenRepo, 'io', 'github', 'rad-ox', 'drift-junit', $version)
    # Maven files of this version; only owned ones are replaced and recorded,
    # an identical file that was already there stays the user's.
    $mavenFiles = @(foreach ($a in @('drift-junit', 'drift-maven-plugin')) {
            foreach ($ext in @('jar', 'pom')) {
                $src = (Join @($here, 'maven', "$a-$version.$ext"))
                [pscustomobject]@{
                    Artifact   = $a
                    Dir        = (Join @($MavenRepo, 'io', 'github', 'rad-ox', $a, $version))
                    Path       = (Join @($MavenRepo, 'io', 'github', 'rad-ox', $a, $version, "$a-$version.$ext"))
                    Source     = $src
                    SourceHash = $sourceHashes[$src]
                    Exists     = $false
                    Different  = $false
                    Owned      = $false
                }
            }
        })

    $old = $null
    if ((Test-Path -LiteralPath $exe) -and -not $testMode) {
        $v = Get-NativeText $exe @('version')
        if ($v -match '^drift (\S+)') { $old = $Matches[1] }
    }
    $what = if (-not $old) { T 'install' 'installazione' }
    elseif ($old -eq $version) { T 'reinstall' 'reinstallazione' }
    else { T "update from $old" "aggiornamento da $old" }
    Write-Host "DRIFT $version  $what"
    if ($DryRun) { Note 'Dry run: nothing changes; these are the steps.' 'Prova: non cambia nulla; ecco i passi.' }

    # Paths of a previous install that move are cleaned up; Maven versions
    # are kept because projects may pin them.
    $oldSkills = [System.Collections.Generic.List[string]]::new()
    $oldHooks = [System.Collections.Generic.List[string]]::new()
    $oldMavens = [System.Collections.Generic.List[string]]::new()
    $oldPath = $false
    if (Test-Path -LiteralPath $manifest) {
        foreach ($line in Get-Content -LiteralPath $manifest) {
            $kind, $path = $line -split "`t", 2
            if ($kind -eq 'skill' -and $path) { $oldSkills.Add($path) }
            elseif ($kind -eq 'hook' -and $path) {
                $oldHooks.Add($path)
                if (-not $hooksSet) { $withHooks = $true }
            }
            elseif ($kind -eq 'path' -and $path -and (Test-SameDir $path $bin)) { $oldPath = $true }
            elseif ($kind -eq 'maven' -and $path) {
                # Older manifests tracked the bridge's version directory.
                $isCurrentDir = Test-SameDir $path $mavenDir
                $current = $isCurrentDir
                foreach ($f in $mavenFiles) {
                    if ((Test-SameDir $path $f.Path) -or ($isCurrentDir -and $f.Artifact -eq 'drift-junit')) {
                        $current = $true
                        if (-not $NoMaven) { $f.Owned = $true }
                    }
                }
                if (($NoMaven -or -not $current) -and (Test-Path -LiteralPath $path)) {
                    $oldMavens.Add($path)
                }
            }
        }
    }
    if (-not $NoMaven) {
        foreach ($item in $mavenFiles) {
            if (Test-Path -LiteralPath $item.Path) {
                if (-not (Test-Path -LiteralPath $item.Path -PathType Leaf)) {
                    Stop-Install "Maven artifact path is not a file: $($item.Path)" "Il percorso dell'artefatto Maven non è un file: $($item.Path)"
                }
                $item.Exists = $true
                if (-not $item.SourceHash) {
                    $item.SourceHash = (Get-FileHash -LiteralPath $item.Source -Algorithm SHA256).Hash.ToLowerInvariant()
                }
                $item.Different = (Get-FileHash -LiteralPath $item.Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.SourceHash
                if (-not $item.Owned -and $item.Different) {
                    Stop-Install "A different Maven artifact already exists at $($item.Path); back it up or use -MavenRepo DIR." `
                        "Esiste già un artefatto Maven diverso in $($item.Path); fanne una copia o usa -MavenRepo DIR."
                }
            }
        }
    }

    Invoke-Step "copy drift.exe to $bin" {
        New-Item -ItemType Directory -Force -Path $bin | Out-Null
        try {
            Copy-Item -LiteralPath $pkgExe -Destination $exe -Force
        } catch {
            Stop-Install "Cannot replace $exe; close any running drift and retry." `
                "Impossibile sostituire $exe; chiudi eventuali drift in esecuzione e riprova."
        }
    }
    foreach ($f in @('install.ps1', 'uninstall.cmd', 'VERSION', 'INSTALL.md', 'INSTALL.it.md', 'SHA256SUMS')) {
        if (Test-Path -LiteralPath (Join @($here, $f))) {
            Invoke-Step "copy $f to $Prefix" { Copy-Item -LiteralPath (Join @($here, $f)) -Destination (Join @($Prefix, $f)) -Force }
        }
    }
    Remove-Safely (Join @($Prefix, 'example')) 'example'
    Invoke-Step "copy example to $Prefix" { Copy-Item -LiteralPath (Join @($here, 'example')) -Destination (Join @($Prefix, 'example')) -Recurse -Force }
    if (Test-Path -LiteralPath (Join @($here, 'bridges'))) {
        Remove-Safely (Join @($Prefix, 'bridges')) 'bridges'
        Invoke-Step "copy bridges to $Prefix" { Copy-Item -LiteralPath (Join @($here, 'bridges')) -Destination (Join @($Prefix, 'bridges')) -Recurse -Force }
        Ok "JS and Python bridges -> $(Show-Path (Join @($Prefix, 'bridges')))" "bridge JS e Python -> $(Show-Path (Join @($Prefix, 'bridges')))"
    }
    if (Test-Path -LiteralPath (Join @($here, 'schemas'))) {
        Remove-Safely (Join @($Prefix, 'schemas')) 'schemas'
        Invoke-Step "copy schemas to $Prefix" { Copy-Item -LiteralPath (Join @($here, 'schemas')) -Destination (Join @($Prefix, 'schemas')) -Recurse -Force }
    }
    if (Test-Path -LiteralPath (Join @($here, 'hooks'))) {
        Invoke-Step "copy hooks to $Prefix" {
            New-Item -ItemType Directory -Force -Path (Join @($Prefix, 'hooks')) | Out-Null
            foreach ($name in @('drift-hook.sh', 'drift-hook.ps1', 'drift-pi.ts')) {
                Copy-Item -LiteralPath (Join @($here, 'hooks', $name)) -Destination (Join @($Prefix, 'hooks', $name)) -Force
            }
        }
    }
    if ($onWindows) {
        Invoke-Step 'unblock the installed files' {
            Get-ChildItem -LiteralPath $Prefix -Recurse -File | Unblock-File
        }
    }
    Ok "drift $version -> $(Show-Path $exe)" "drift $version -> $(Show-Path $exe)"

    $piDir = if ($env:PI_CODING_AGENT_DIR) { $env:PI_CODING_AGENT_DIR } else { Join @([string]$HOME, '.pi', 'agent') }
    $detectedAgents = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath (Join @([string]$HOME, '.agents'))) { $detectedAgents.Add('agents') }
    if ((Test-Path -LiteralPath (Join @([string]$HOME, '.pi'))) -or (Test-Path -LiteralPath $piDir)) { $detectedAgents.Add('pi') }
    foreach ($ag in @('copilot', 'claude', 'codex', 'cursor', 'gemini')) {
        if (Test-Path -LiteralPath (Join @([string]$HOME, ".$ag"))) { $detectedAgents.Add($ag) }
    }

    if (-not $hooksSet -and -not $DryRun) {
        if ($env:DRIFT_ASSUME_TTY -eq '1' -or (-not $testMode -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected)) {
            $agLabel = if ($detectedAgents.Count -gt 0) { $detectedAgents -join ', ' } else { 'pi, copilot, agents' }
            $promptMsg = T "  ? Install automatic DRIFT hooks for agents ($agLabel)? [Y/n] " `
                "  ? Installare gli hook automatici di DRIFT per gli agenti ($agLabel)? [S/n] "
            Write-Host $promptMsg -NoNewline
            $ans = [Console]::In.ReadLine()
            if ($null -eq $ans) { $ans = '' } else { $ans = $ans.Trim() }
            if ($ans -match '^(?i)(|y|yes|s|si|sì)$') { $withHooks = $true } else { $withHooks = $false }
        }
    }

    $releaseDir = Join @($Prefix, 'hooks', 'release')
    $withUpdateCheck = Test-Path -LiteralPath $releaseDir -PathType Container
    if ($UpdateCheck) { $withUpdateCheck = $true }
    if ($NoUpdateCheck -or -not $withHooks) { $withUpdateCheck = $false }
    if ($withHooks -and -not $UpdateCheck -and -not $NoUpdateCheck -and -not $DryRun -and
        ($env:DRIFT_ASSUME_TTY -eq '1' -or (-not $testMode -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected))) {
        Write-Host (T '  ? Install optional GitHub release checks at session start? [Y/n] ' `
            '  ? Installare il controllo opzionale delle release GitHub a inizio sessione? [S/n] ') -NoNewline
        $answer = [Console]::In.ReadLine()
        if ($null -ne $answer) { $withUpdateCheck = $answer.Trim() -match '^(?i)(|y|yes|s|si)$' }
        else { Note 'No installation answer; preserving the existing release-check choice.' 'Nessuna risposta; mantengo la scelta precedente.' }
    }
    if ($withUpdateCheck) {
        Invoke-Step "install optional release checks to $releaseDir" {
            New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
            foreach ($name in @('check.py', 'check.ps1', 'release-policy.json')) {
                Copy-Item -LiteralPath (Join @($here, 'release', $name)) -Destination (Join @($releaseDir, $name)) -Force
            }
        }
    } elseif (Test-Path -LiteralPath $releaseDir) {
        Invoke-Step "remove optional release checks from $releaseDir" {
            foreach ($name in @('check.py', 'check.ps1', 'release-policy.json')) {
                $file = Join @($releaseDir, $name)
                if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
            }
            [IO.Directory]::Delete($releaseDir)
        }
    }

    $newSkills = [System.Collections.Generic.List[string]]::new()
    function Install-SkillTo([string]$TargetSkillsRoot) {
        foreach ($sName in @('drift', 'drift-recall')) {
            $srcSkill = Join @($here, 'skill', $sName)
            if (-not (Test-Path -LiteralPath $srcSkill)) { continue }
            $targetSkill = Join @($TargetSkillsRoot, $sName)
            $staging = Join @($TargetSkillsRoot, ".$sName.new")
            Remove-Safely $staging ".$sName.new"
            Invoke-Step "copy the agent skill to $targetSkill" {
                New-Item -ItemType Directory -Force -Path $TargetSkillsRoot | Out-Null
                Copy-Item -LiteralPath $srcSkill -Destination $staging -Recurse -Force
            }
            Remove-Safely $targetSkill $sName
            Invoke-Step "move $staging to $targetSkill" { Move-Item -LiteralPath $staging -Destination $targetSkill }
            $newSkills.Add($targetSkill)
            Ok "agent skill -> $(Show-Path $targetSkill)" "skill dell'agente -> $(Show-Path $targetSkill)"
        }
    }

    if (-not $NoSkill) {
        Install-SkillTo $SkillsDir
        if (-not $skillsSet) {
            $agentsSkills = Join @([string]$HOME, '.agents', 'skills')
            $hasNeutral = (Test-Path -LiteralPath (Join @([string]$HOME, '.agents'))) -or
                (Test-Path -LiteralPath (Join @([string]$HOME, '.pi'))) -or
                (Test-Path -LiteralPath $piDir) -or
                (Test-Path -LiteralPath (Join @([string]$HOME, '.codex'))) -or
                (Test-Path -LiteralPath (Join @([string]$HOME, '.cursor'))) -or
                $withHooks
            if ($hasNeutral -and -not (Test-SameDir $SkillsDir $agentsSkills)) {
                Install-SkillTo $agentsSkills
            }
            $claudeSkills = Join @([string]$HOME, '.claude', 'skills')
            if ((Test-Path -LiteralPath (Join @([string]$HOME, '.claude'))) -and -not (Test-SameDir $SkillsDir $claudeSkills)) {
                Install-SkillTo $claudeSkills
            }
        }
    }
    $newSkillsSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($sNew in $newSkills) {
        [void]$newSkillsSet.Add([Environment]::ExpandEnvironmentVariables($sNew).Trim().TrimEnd('\'))
    }
    foreach ($sOld in $oldSkills) {
        $normOld = [Environment]::ExpandEnvironmentVariables($sOld).Trim().TrimEnd('\')
        if (-not $newSkillsSet.Contains($normOld) -and (Test-Skill $sOld)) {
            $sLeaf = Split-Path -Leaf $sOld
            if ($sLeaf -in @('drift', 'drift-recall')) {
                Remove-Safely $sOld $sLeaf
            }
            foreach ($up in @((Split-Path $sOld), (Split-Path (Split-Path $sOld)))) {
                if (-not $DryRun -and $up -and (Test-Path -LiteralPath $up -PathType Container) -and
                    -not (Get-ChildItem -LiteralPath $up -Force | Select-Object -First 1)) {
                    Remove-Item -LiteralPath $up -Force
                }
            }
            Ok "removed the previous skill $(Show-Path $sOld)" "rimossa la skill precedente $(Show-Path $sOld)"
        }
    }

    $newHooks = [System.Collections.Generic.List[string]]::new()
    function Write-PiExtension([string]$Target) {
        Invoke-Step "copy Pi extension to $Target" {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
            $template = Get-Content -LiteralPath (Join @($here, 'hooks', 'drift-pi.ts')) -Raw
            $marker = 'const releaseDirectory = "";'
            if (($template.Split(@($marker), [StringSplitOptions]::None)).Count -ne 2) {
                throw 'Pi release component marker missing or ambiguous'
            }
            $directory = if ($withUpdateCheck) { $releaseDir } else { '' }
            $replacement = 'const releaseDirectory = ' + (ConvertTo-Json -InputObject $directory -Compress) + ';'
            [IO.File]::WriteAllText($Target, $template.Replace($marker, $replacement))
        }
    }
    function Write-DropinHook([string]$TargetFile) {
        $hookPs1 = (Join @($Prefix, 'hooks', 'drift-hook.ps1')) -replace '\\', '\\'
        $json = @"
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "type": "command",
        "bash": "~/.local/share/drift/hooks/drift-hook.sh session",
        "command": "~/.local/share/drift/hooks/drift-hook.sh session",
        "powershell": "powershell -NoProfile -ExecutionPolicy Bypass -File \"$hookPs1\" -Mode session",
        "timeoutSec": 5
      }
    ],
    "userPromptSubmitted": [
      {
        "type": "command",
        "bash": "~/.local/share/drift/hooks/drift-hook.sh prompt",
        "command": "~/.local/share/drift/hooks/drift-hook.sh prompt",
        "powershell": "powershell -NoProfile -ExecutionPolicy Bypass -File \"$hookPs1\" -Mode prompt",
        "timeoutSec": 5
      }
    ],
    "agentStop": [
      {
        "type": "command",
        "bash": "~/.local/share/drift/hooks/drift-hook.sh stop",
        "command": "~/.local/share/drift/hooks/drift-hook.sh stop",
        "powershell": "powershell -NoProfile -ExecutionPolicy Bypass -File \"$hookPs1\" -Mode stop",
        "timeoutSec": 10
      }
    ]
  }
}
"@
        Invoke-Step "write hook to $TargetFile" {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $TargetFile) | Out-Null
            [IO.File]::WriteAllText($TargetFile, $json)
        }
        $newHooks.Add($TargetFile)
        Ok "agent hook -> $(Show-Path $TargetFile)" "hook dell'agente -> $(Show-Path $TargetFile)"
    }

    if ($withHooks -and (Test-Path -LiteralPath (Join @($here, 'hooks')))) {
        if ($HooksDir) {
            Write-DropinHook (Join @($HooksDir, 'drift.json'))
        } else {
            $anyAgent = $false
            if ($detectedAgents.Contains('pi')) {
                $anyAgent = $true
                $piExt = Join @($piDir, 'extensions', 'drift.ts')
                Write-PiExtension $piExt
                $newHooks.Add($piExt)
                Ok "Pi extension -> $(Show-Path $piExt)" "estensione Pi -> $(Show-Path $piExt)"
            }
            if ($detectedAgents.Contains('copilot')) {
                $anyAgent = $true
                Write-DropinHook (Join @([string]$HOME, '.copilot', 'hooks', 'drift.json'))
            }
            if ($detectedAgents.Contains('cursor')) {
                $anyAgent = $true
                Write-DropinHook (Join @([string]$HOME, '.cursor', 'hooks', 'drift.json'))
            }
            if (-not $anyAgent) {
                $piExt = Join @($piDir, 'extensions', 'drift.ts')
                Write-PiExtension $piExt
                $newHooks.Add($piExt)
                Ok "Pi extension -> $(Show-Path $piExt)" "estensione Pi -> $(Show-Path $piExt)"
                Write-DropinHook (Join @([string]$HOME, '.copilot', 'hooks', 'drift.json'))
            }
        }
    }
    $newHooksSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($hNew in $newHooks) {
        [void]$newHooksSet.Add([Environment]::ExpandEnvironmentVariables($hNew).Trim().TrimEnd('\'))
    }
    foreach ($hOld in $oldHooks) {
        $normOld = [Environment]::ExpandEnvironmentVariables($hOld).Trim().TrimEnd('\')
        if (-not $newHooksSet.Contains($normOld) -and (Test-Path -LiteralPath $hOld -PathType Leaf)) {
            $leaf = Split-Path -Leaf $hOld
            if ($leaf -in @('drift.json', 'drift.ts', 'hooks.json', 'settings.json')) {
                Remove-Safely $hOld $leaf
                foreach ($up in @((Split-Path $hOld), (Split-Path (Split-Path $hOld)), (Split-Path (Split-Path (Split-Path $hOld))))) {
                    if (-not $DryRun -and $up -and (Test-Path -LiteralPath $up -PathType Container) -and
                        -not (Get-ChildItem -LiteralPath $up -Force | Select-Object -First 1)) {
                        Remove-Item -LiteralPath $up -Force
                    }
                }
                Ok "removed the previous hook $(Show-Path $hOld)" "rimosso l'hook precedente $(Show-Path $hOld)"
            }
        }
    }

    if (-not $NoMaven) {
        foreach ($item in $mavenFiles) {
            if (-not $item.Exists) { $item.Owned = $true }
        }
        Invoke-Step "copy drift-junit and drift-maven-plugin $version to $(Join @($MavenRepo, 'io', 'github', 'rad-ox'))" {
            foreach ($item in $mavenFiles) {
                New-Item -ItemType Directory -Force -Path $item.Dir | Out-Null
                if ((-not $item.Exists) -or ($item.Owned -and $item.Different)) {
                    $staged = $item.Path + '.new'
                    Remove-Safely $staged '.new'
                    Copy-Item -LiteralPath $item.Source -Destination $staged -Force
                    Move-Item -LiteralPath $staged -Destination $item.Path -Force
                }
            }
        }
        Ok "JUnit bridge io.github.rad-ox:drift-junit:$version -> $(Show-Path $mavenDir)" `
            "bridge JUnit io.github.rad-ox:drift-junit:$version -> $(Show-Path $mavenDir)"
        $pluginDir = Join @($MavenRepo, 'io', 'github', 'rad-ox', 'drift-maven-plugin', $version)
        Ok "Maven plugin io.github.rad-ox:drift-maven-plugin:$version -> $(Show-Path $pluginDir)" `
            "plugin Maven io.github.rad-ox:drift-maven-plugin:$version -> $(Show-Path $pluginDir)"
    }

    $pathAdded = $false
    if ($onWindows -and -not $NoPath) {
        $userPath = Get-UserPath
        $present = @($userPath -split ';' | Where-Object { $_ -and (Test-SameDir $_ $bin) }).Count -gt 0
        if (-not $present) {
            Invoke-Step "add $bin to the user PATH" {
                Set-UserPath ((@($userPath -split ';' | Where-Object { $_ }) + $bin) -join ';')
            }
            $pathAdded = $true
            Ok 'added to the user PATH' 'aggiunto al PATH utente'
        }
        if (-not (@($env:Path -split ';' | Where-Object { $_ -and (Test-SameDir $_ $bin) }).Count)) {
            $env:Path = ($env:Path.TrimEnd(';') + ';' + $bin)
        }
    }

    if ($onWindows) {
        Invoke-Step "register DRIFT in Settings > Apps ($arpKey)" {
            $size = [int]((Get-ChildItem -LiteralPath $Prefix -Recurse -File | Measure-Object -Sum Length).Sum / 1KB)
            New-Item -Path $arpKey -Force | Out-Null
            $uninstallCmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join @($Prefix, 'install.ps1')) + '" -Uninstall'
            $values = @{
                DisplayName     = 'DRIFT'
                DisplayVersion  = $version
                Publisher       = 'DRIFT'
                InstallLocation = $Prefix
                DisplayIcon     = $exe
                UninstallString = $uninstallCmd
                InstallDate     = (Get-Date -Format 'yyyyMMdd')
            }
            foreach ($k in $values.Keys) { New-ItemProperty -Path $arpKey -Name $k -Value $values[$k] -PropertyType String -Force | Out-Null }
            foreach ($k in @('NoModify', 'NoRepair')) { New-ItemProperty -Path $arpKey -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
            New-ItemProperty -Path $arpKey -Name EstimatedSize -Value $size -PropertyType DWord -Force | Out-Null
        }
    }

    if ($DryRun) {
        Write-Host (T 'Dry run complete: nothing was changed.' 'Prova completata: non è cambiato nulla.')
        exit 0
    }

    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("version`t$version")
    $lines.Add("bin`t$exe")
    foreach ($s in $newSkills) { $lines.Add("skill`t$s") }
    foreach ($h in $newHooks) { $lines.Add("hook`t$h") }
    if (-not $NoMaven) {
        foreach ($f in $mavenFiles) { if ($f.Owned) { $lines.Add("maven`t$($f.Path)") } }
    }
    foreach ($m in $oldMavens) { $lines.Add("maven`t$m") }
    if ($pathAdded -or $oldPath) { $lines.Add("path`t$bin") }
    [IO.File]::WriteAllLines($manifest, $lines)

    # ---- verification and environment
    $example = Join @($Prefix, 'example', '.drift')
    if ($testMode) {
        Note 'self-test skipped: not on Windows' 'autotest saltato: non è Windows'
    } else {
        $v = Get-NativeText $exe @('version')
        if (-not ($v -match "^drift $([regex]::Escape($version))")) {
            Stop-Install "The installed drift does not run: $v" "Il drift installato non parte: $v"
        }
        $null = Get-NativeText $exe @('check', $example)
        if ($LASTEXITCODE -ne 0) {
            Stop-Install 'self-test failed: drift check of the bundled example' "autotest fallito: drift check sull'esempio incluso"
        }
        Ok 'self-test: drift checks the bundled example' "autotest: drift verifica l'esempio incluso"
    }

    if (-not $NoMaven) {
        $jv = Get-NativeText 'java' @('-version')
        if (-not $jv) {
            Note 'Java not found: the JUnit bridge needs JDK 17+ (winget install Microsoft.OpenJDK.21)' `
                'Java non trovato: il bridge JUnit richiede JDK 17+ (winget install Microsoft.OpenJDK.21)'
        } elseif ($jv -match 'version "(1\.)?(\d+)') {
            $major = [int]$Matches[2]
            if ($major -lt 17) { Note "Java ${major} found: the JUnit bridge needs JDK 17+" "Trovato Java ${major}: il bridge JUnit richiede JDK 17+" }
            else { Ok "Java $major" "Java $major" }
        }
        $mv = Get-NativeText 'mvn' @('-v')
        if ($mv -and $mv -match 'Maven (\d+(\.\d+)+)') { Ok "Maven $($Matches[1])" "Maven $($Matches[1])" }
        else {
            Note 'Maven not found: needed only to run your tests (https://maven.apache.org/install.html)' `
                'Maven non trovato: serve solo per eseguire i test (https://maven.apache.org/install.html)'
        }
    }

    $guide = Join @($Prefix, (T 'INSTALL.md' 'INSTALL.it.md'))
    Write-Host ''
    if ($pathAdded -or $NoPath -or -not $onWindows) {
        Write-Host (T 'Ready. Open a new terminal, then try:' 'Pronto. Apri un nuovo terminale e prova:')
    } else {
        Write-Host (T 'Ready. Try:' 'Pronto. Prova:')
    }
    Write-Host "  drift check `"$example`""
    Write-Host '  drift help'
    Write-Host ((T 'Guide:     ' 'Guida:      ') + $guide)
    Write-Host ((T 'Uninstall: Settings > Apps > DRIFT, or ' 'Rimozione: Impostazioni > App > DRIFT, oppure ') + (Join @($Prefix, 'uninstall.cmd')))
} catch {
    $code = 1
    if ($color) { Write-Host ('x ' + $_.Exception.Message) -ForegroundColor Red } else { Write-Host ('x ' + $_.Exception.Message) }
} finally {
    if ($pause) { Read-Host (T 'Press Enter to close' 'Premi Invio per chiudere') | Out-Null }
}
exit $code
