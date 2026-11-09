[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$DriftExe)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

function Read-Version([string]$Value) {
    $pattern = '\Av?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\z'
    $match = [regex]::Match($Value, $pattern)
    if (-not $match.Success) { throw 'invalid version' }
    return ,@($match.Groups[1].Value, $match.Groups[2].Value, $match.Groups[3].Value, $match.Groups[4].Value)
}

function Get-ReleaseMetadata($Policy, [int]$RemainingMilliseconds) {
    Add-Type -AssemblyName System.Net.Http
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseDefaultCredentials = $false
    $handler.UseCookies = $false
    $client = [Net.Http.HttpClient]::new($handler)
    try {
        $client.Timeout = [TimeSpan]::FromSeconds($Policy.timeout_seconds)
        $client.MaxResponseContentBufferSize = $Policy.max_response_bytes
        $client.DefaultRequestHeaders.Add('Accept', 'application/vnd.github+json')
        $client.DefaultRequestHeaders.Add('User-Agent', 'drift-release-check')
        $task = $client.GetAsync("https://api.github.com/repos/$($Policy.repository)/releases/latest")
        if (-not $task.Wait($RemainingMilliseconds)) { $client.CancelPendingRequests(); throw 'release check deadline' }
        $response = $task.Result
        [void]$response.EnsureSuccessStatusCode()
        return ($response.Content.ReadAsStringAsync().Result | ConvertFrom-Json)
    } finally { $client.Dispose() }
}

function Invoke-DriftReleaseCheck([string]$DriftExe) {
    if ($env:DRIFT_UPDATE_CHECK -eq '0') { return }
    $process = $null
    $watch = [Diagnostics.Stopwatch]::StartNew()
    try {
        $policy = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release-policy.json') -Raw | ConvertFrom-Json
        if ($policy.enabled -isnot [bool] -or $policy.channel -cne 'stable' -or
            $policy.repository -isnot [string] -or $policy.repository -cnotmatch '\A[A-Za-z0-9-]+/[A-Za-z0-9_.-]+\z') {
            throw 'invalid release policy'
        }
        if (($policy.repository -split '/')[1] -in @('.', '..')) { throw 'invalid release repository' }
        foreach ($key in @('timeout_seconds', 'total_timeout_seconds', 'max_response_bytes')) {
            if ($policy.$key -isnot [int] -and $policy.$key -isnot [long]) { throw 'invalid release policy' }
            if ($policy.$key -le 0) { throw 'invalid release policy' }
        }
        if ($policy.timeout_seconds -ge $policy.total_timeout_seconds -or
            $policy.total_timeout_seconds -gt 3 -or $policy.max_response_bytes -gt 65536) {
            throw 'invalid release limits'
        }
        if (-not $policy.enabled) { return }
        function Remaining {
            $ms = [int]($policy.total_timeout_seconds * 1000 - $watch.ElapsedMilliseconds)
            if ($ms -le 0) { throw 'release check deadline' }
            return $ms
        }
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = [Diagnostics.ProcessStartInfo]::new($DriftExe, 'version')
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardOutput = $true
        $process.StartInfo.RedirectStandardError = $true
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        [void]$process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit((Remaining))) { $process.Kill(); throw 'CLI version deadline' }
        if ($process.ExitCode -ne 0) { throw 'CLI version unavailable' }
        $fields = $stdout.Result.Trim() -split '\s+'
        if ($fields.Count -lt 2 -or $fields[0] -cne 'drift') { throw 'invalid CLI version' }
        $installed = $fields[1]
        $localVersion = Read-Version $installed
        $release = Get-ReleaseMetadata $policy (Remaining)
        if ($release.draft -isnot [bool] -or $release.prerelease -isnot [bool]) { throw 'invalid release metadata' }
        if ($release.draft -or $release.prerelease) { return }
        if ($release.tag_name -isnot [string]) { throw 'invalid release tag' }
        $remoteVersion = Read-Version $release.tag_name
        if ($remoteVersion[3]) { throw 'invalid stable release tag' }
        $comparison = 0
        for ($i = 0; $i -lt 3; $i++) {
            $comparison = $remoteVersion[$i].Length.CompareTo($localVersion[$i].Length)
            if ($comparison -eq 0) { $comparison = [string]::CompareOrdinal($remoteVersion[$i], $localVersion[$i]) }
            if ($comparison -ne 0) { break }
        }
        if ($comparison -gt 0 -or ($comparison -eq 0 -and $localVersion[3])) {
            $available = $release.tag_name -creplace '^v', ''
            Write-Output "DRIFT update available: $installed -> $available. Release: https://github.com/$($policy.repository)/releases/tag/$($release.tag_name)"
        }
    } catch {
        [Console]::Error.WriteLine('drift: release check unavailable; continuing without an update verdict.')
    } finally {
        if ($process) { $process.Dispose() }
    }
}

if ($MyInvocation.InvocationName -ne '.') { Invoke-DriftReleaseCheck $DriftExe }
