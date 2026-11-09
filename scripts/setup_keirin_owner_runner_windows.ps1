#requires -Version 5.1
<#
Run this ON YOUR OWN Windows x64 computer as Administrator.
Preinstall/authenticate GitHub CLI (gh), Python 3, and extract the official
GitHub Windows x64 Actions runner archive under RunnerRoot.
This setup REFUSES public repos, missing preexisting private SQLite,
and unlabelled/offline runners. Never paste tokens into ChatGPT.
#>
[CmdletBinding()]
param(
  [string]$Repo = 'haji84/RACE-AI',
  [Parameter(Mandatory = $true)][string]$DbPath,
  [Parameter(Mandatory = $true)][string]$InboxPath,
  [string]$RunnerRoot = 'C:\actions-runner-keirin',
  [string]$GrantManifestPath = '',
  [switch]$PersonalResearchOnly,
  [switch]$EnablePublicSourceFetch
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Require-Exit([string]$Reason) {
  if ($LASTEXITCODE -ne 0) { throw $Reason }
}
function Existing-Path([string]$Value, [bool]$Directory) {
  if (-not [IO.Path]::IsPathRooted($Value)) { throw 'ABSOLUTE_PATH_REQUIRED' }
  if (-not (Test-Path -LiteralPath $Value)) { throw 'PRIVATE_PATH_MISSING' }
  $item=Get-Item -LiteralPath $Value -Force
  if ($Directory -ne $item.PSIsContainer) { throw 'FILE_DIRECTORY_TYPE_MISMATCH' }
  if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'PRIVATE_SYMLINK_REFUSED'
  }
  return $item.FullName
}
if ($env:OS -ne 'Windows_NT' -or [IntPtr]::Size -ne 8) {
  throw 'WINDOWS_X64_REQUIRED'
}
if ($Repo -ne 'haji84/RACE-AI') { throw 'UNEXPECTED_REPOSITORY' }
foreach ($name in @('gh','python')) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "MISSING_PROGRAM_$name"
  }
}
& gh auth status *> $null
Require-Exit 'RUN_GH_AUTH_LOGIN_LOCALLY'
$privacy = & gh api "repos/$Repo" --jq '.private'
Require-Exit 'GITHUB_REPOSITORY_PRIVACY_UNVERIFIED'
if (($privacy | Out-String).Trim().ToLowerInvariant() -ne 'true') {
  throw 'PUBLIC_REPOSITORY_UNSAFE_FOR_PRIVATE_SELF_HOSTED_RUNNER'
}
$hasGrant = -not [string]::IsNullOrWhiteSpace($GrantManifestPath)
if ($hasGrant -eq $PersonalResearchOnly.IsPresent) {
  throw 'CHOOSE_EXACTLY_ONE_LICENSE_MANIFEST_OR_PERSONAL_RESEARCH_MODE'
}
$db = Existing-Path $DbPath $false
$inbox = Existing-Path $InboxPath $true
$grant = ''
if ($hasGrant) { $grant = Existing-Path $GrantManifestPath $false }
if (-not [IO.Path]::IsPathRooted($RunnerRoot)) {
  throw 'RUNNER_DIRECTORY_MUST_BE_ABSOLUTE'
}
$root = [IO.Path]::GetFullPath($RunnerRoot).TrimEnd('\')
foreach ($item in @($db, $inbox, $grant)) {
  if ($item -and ($item -eq $root -or $item.StartsWith(
       $root + '\',[StringComparison]::OrdinalIgnoreCase))) {
    throw 'OWNER_PRIVATE_DATA_INSIDE_RUNNER_WORK_DIRECTORY'
  }
}
# Read-only SQLite integrity and minimum existing tables.
$py = @'
import os,sqlite3,sys
path=sys.argv[1]
if not os.path.isfile(path):sys.exit(2)
db=sqlite3.connect("file:"+path.replace("\\","/")+"?mode=ro",uri=True,timeout=4)
try:
    assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    names={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"forecasts","result_revisions"}.issubset(names)
finally:
    db.close()
'@
& python -c $py $db
Require-Exit 'OWNER_SQLITE_PREEXISTING_SCHEMA_OR_INTEGRITY_FAILED'
$config=Join-Path $root 'config.cmd'
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
  throw 'EXTRACT_OFFICIAL_GITHUB_RUNNER_WINDOWS_X64_TO_RUNNER_ROOT'
}
$runName="$env:COMPUTERNAME-keirin-private"
$localSettings=Join-Path $root '.runner'
if (Test-Path -LiteralPath $localSettings -PathType Leaf) {
  $settings=Get-Content -LiteralPath $localSettings -Raw | ConvertFrom-Json
  if ($settings.gitHubUrl -ne "https://github.com/$Repo" -or
      [string]::IsNullOrWhiteSpace($settings.agentName)) {
    throw 'EXISTING_RUNNER_IS_FOR_A_DIFFERENT_REPOSITORY'
  }
  $runName=[string]$settings.agentName
} else {
  $admin=([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $admin) { throw 'RUN_POWERSHELL_AS_ADMINISTRATOR' }
  $token=& gh api --method POST "repos/$Repo/actions/runners/registration-token" --jq '.token'
  Require-Exit 'REGISTRATION_TOKEN_REQUEST_DENIED'
  if ([string]::IsNullOrWhiteSpace($token)) { throw 'REGISTRATION_TOKEN_MISSING' }
  Push-Location $root
  try {
    $flags=@('--unattended','--url',"https://github.com/$Repo",
             '--token',$token,'--name',$runName,'--labels','keirin-owner-private',
             '--work','_work','--runasservice')
    & '.\config.cmd' @flags
    Require-Exit 'GITHUB_RUNNER_WINDOWS_SERVICE_CONFIGURATION_FAILED'
  } finally {
    Pop-Location
    $token=$null
  }
}
$raw=& gh api "repos/$Repo/actions/runners"
Require-Exit 'RUNNER_INVENTORY_UNAVAILABLE'
$runner=(($raw | ConvertFrom-Json).runners | Where-Object {
  $_.name -eq $runName } | Select-Object -First 1)
if ($null -eq $runner) { throw 'RUNNER_NOT_REGISTERED' }
$labels=@($runner.labels | ForEach-Object { $_.name })
foreach ($label in @('self-hosted','Windows','X64','keirin-owner-private')) {
  if ($labels -notcontains $label) { throw 'RUNNER_REQUIRED_LABEL_MISSING' }
}
if ($runner.status -ne 'online') { throw 'RUNNER_NOT_YET_ONLINE' }
# Do not publish values, database bytes, private source or vendor tokens.
& gh secret set RACE_AI_KEIRIN_OWNER_DB --repo $Repo --body $db
Require-Exit 'OWNER_DB_SECRET_FAILED'
& gh secret set RACE_AI_KEIRIN_OWNER_INBOX --repo $Repo --body $inbox
Require-Exit 'OWNER_INBOX_SECRET_FAILED'
if ($grant) {
  & gh secret set RACE_AI_KEIRIN_OWNER_GRANT_MANIFEST --repo $Repo --body $grant
  Require-Exit 'OWNER_GRANT_MANIFEST_SECRET_FAILED'
} else {
  # Avoid inheriting a stale manifest from a previous licensed configuration.
  $listed=& gh secret list --repo $Repo --json name
  Require-Exit 'OWNER_SECRET_INVENTORY_UNAVAILABLE'
  $names=@(($listed | ConvertFrom-Json) | ForEach-Object { $_.name })
  if ($names -contains 'RACE_AI_KEIRIN_OWNER_GRANT_MANIFEST') {
    & gh secret delete RACE_AI_KEIRIN_OWNER_GRANT_MANIFEST --repo $Repo
    Require-Exit 'STALE_GRANT_MANIFEST_SECRET_NOT_REMOVED'
  }
}
$fetchValue = if ($EnablePublicSourceFetch) { 'true' } else { 'false' }
& gh variable set RACE_AI_KEIRIN_OWNER_PUBLIC_FETCH_ENABLED --repo $Repo --body $fetchValue
Require-Exit 'OWNER_FETCH_VARIABLE_FAILED'
# Only now opt-in to the existing GitHub cron-controlled private model job.
& gh variable set RACE_AI_KEIRIN_OWNER_RUNTIME_ENABLED --repo $Repo --body 'true'
Require-Exit 'OWNER_RUNTIME_VARIABLE_FAILED'
Write-Output 'OWNER_WINDOWS_RUNNER_REGISTERED_AND_GITHUB_CRON_ENABLED'
Write-Output 'A real PR71 four-model forecast requires a complete licensed pre-cutoff input; setup is not proof of forecast success.'
