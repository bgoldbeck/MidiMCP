<#
.SYNOPSIS
  Build the MidiMCP Docker image and publish it to GitHub Container Registry (ghcr.io).

.DESCRIPTION
  Runs on your Windows PC with Docker Desktop and Git installed. No GitHub Actions or
  paid services: ghcr.io is free for public images.
  Usually started by double-clicking scripts\publish-image.cmd.

  Steps: check tools -> check Docker -> check repository -> build -> log in -> push -> log out.
  Build output is shown live (errors in red) and saved to publish-image.log in the repo root.

.PARAMETER Owner
  GitHub user that owns the image (default: bgoldbeck). Image: ghcr.io/<owner>/midimcp

.PARAMETER NoPush
  Build only; do not log in or push.

.EXAMPLE
  scripts\publish-image.cmd
  scripts\publish-image.cmd -NoPush
#>
param(
    [string]$Owner = "bgoldbeck",
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
$script:StepNumber = 0
$script:TotalSteps = 7
$script:Started = Get-Date

# ----------------------------------------------------------------- output helpers

function Write-Banner([string]$Text) {
    $line = "=" * 70
    Write-Host ""
    Write-Host $line -ForegroundColor DarkCyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor DarkCyan
}

function Write-Step([string]$Text) {
    $script:StepNumber++
    $script:StepStarted = Get-Date
    Write-Host ""
    Write-Host ("[{0}/{1}] {2}" -f $script:StepNumber, $script:TotalSteps, $Text) -ForegroundColor Cyan
}

function Write-Ok([string]$Text) {
    $seconds = ((Get-Date) - $script:StepStarted).TotalSeconds
    Write-Host ("  OK   {0}  ({1:N1}s)" -f $Text, $seconds) -ForegroundColor Green
}

function Write-Info([string]$Text) {
    Write-Host "  ..   $Text" -ForegroundColor Gray
}

function Write-Warn([string]$Text) {
    Write-Host "  WARN $Text" -ForegroundColor Yellow
}

function Stop-WithError([string]$Text, [string]$Hint) {
    Write-Host ""
    Write-Host "  FAILED: $Text" -ForegroundColor Red
    if ($Hint) {
        Write-Host "  HOW TO FIX: $Hint" -ForegroundColor Yellow
    }
    Write-Host ""
    exit 1
}

function Invoke-Native {
    <# Run a native command, stream its output with colors, optionally tee to a log.
       Returns the exit code. Docker writes progress to stderr, so stderr is not an error. #>
    param([string]$Exe, [string[]]$Arguments, [string]$LogFile)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object {
            $line = "$_"
            if ($LogFile) { Add-Content -Path $LogFile -Value $line }
            if ($line -match "(?i)(^|\s)(error|failed)\b|denied|unauthorized") {
                Write-Host "    $line" -ForegroundColor Red
            } elseif ($line -match "(?i)warn") {
                Write-Host "    $line" -ForegroundColor Yellow
            } elseif ($line -match "DONE|Pushed|digest:|naming to|Successfully") {
                Write-Host "    $line" -ForegroundColor Green
            } elseif ($line -match "CACHED|Layer already exists") {
                Write-Host "    $line" -ForegroundColor DarkGray
            } else {
                Write-Host "    $line" -ForegroundColor Gray
            }
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Get-NativeOutput([string]$Exe, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        return @{ Code = $LASTEXITCODE; Text = ($output -join "`n").Trim() }
    } finally {
        $ErrorActionPreference = $previous
    }
}

# ------------------------------------------------------------------------ steps

$Owner = $Owner.ToLowerInvariant()
$Image = "ghcr.io/$Owner/midimcp"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogFile = Join-Path $RepoRoot "publish-image.log"
if ($NoPush) { $script:TotalSteps = 4 }

Write-Banner "MidiMCP image publisher  ->  $Image"

# 1. Tools
Write-Step "Checking required tools"
foreach ($tool in @("git", "docker")) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    if (-not $found) {
        if ($tool -eq "docker") {
            Stop-WithError "docker was not found on PATH." "Install Docker Desktop (https://www.docker.com/products/docker-desktop/), start it, then reopen this window."
        }
        Stop-WithError "git was not found on PATH." "Install Git for Windows (https://git-scm.com/download/win), then reopen this window."
    }
    Write-Info "$tool -> $($found.Source)"
}
Write-Ok "git and docker are installed"

# 2. Docker engine
Write-Step "Checking that Docker is running"
$info = Get-NativeOutput "docker" @("info", "--format", "{{.ServerVersion}} ({{.OSType}}/{{.Architecture}})")
if ($info.Code -ne 0) {
    Stop-WithError "Docker is installed but the engine is not reachable." "Start Docker Desktop and wait until it says 'Engine running', then run this again."
}
if ($info.Text -match "windows/") {
    Stop-WithError "Docker Desktop is in Windows-containers mode ($($info.Text))." "Right-click the Docker tray icon -> 'Switch to Linux containers...', then run this again."
}
Write-Ok "Docker engine $($info.Text)"

# 3. Repository state
Write-Step "Checking the repository"
Set-Location $RepoRoot
Write-Info "repo: $RepoRoot"
$branch = (Get-NativeOutput "git" @("rev-parse", "--abbrev-ref", "HEAD")).Text
$commit = (Get-NativeOutput "git" @("rev-parse", "--short", "HEAD")).Text
if (-not $commit) {
    Stop-WithError "This folder is not a git checkout." "Run the script from inside your MidiMCP clone (scripts\publish-image.cmd)."
}
Write-Info "branch $branch at commit $commit"

$dirty = (Get-NativeOutput "git" @("status", "--porcelain")).Text
if ($dirty) {
    Write-Host $dirty -ForegroundColor Yellow
    Stop-WithError "There are uncommitted changes (listed above); the image would not match any commit." "Commit or stash them, or run 'git pull' on a clean checkout."
}

$fetch = Get-NativeOutput "git" @("fetch", "--quiet", "origin", "main")
if ($fetch.Code -ne 0) {
    Write-Warn "Could not reach GitHub to compare with origin/main: $($fetch.Text)"
} else {
    $compare = Get-NativeOutput "git" @("rev-list", "--left-right", "--count", "HEAD...origin/main")
    $ahead = 0
    $behind = 0
    if ($compare.Code -eq 0 -and $compare.Text -match "^(\d+)\s+(\d+)$") {
        $ahead = [int]$Matches[1]
        $behind = [int]$Matches[2]
    } else {
        Write-Warn "Could not compare with origin/main: $($compare.Text)"
    }
    if ($behind -gt 0) {
        Write-Warn "Your checkout is $behind commit(s) behind origin/main. You would publish old code."
        $answer = Read-Host "  Run 'git pull' first? [Y/n]"
        if ($answer -eq "" -or $answer -match "^[Yy]") {
            if ((Invoke-Native "git" @("pull", "--ff-only", "origin", "main")) -ne 0) {
                Stop-WithError "git pull failed." "Resolve the problem shown above (for example local commits), then run this again."
            }
            $commit = (Get-NativeOutput "git" @("rev-parse", "--short", "HEAD")).Text
            Write-Info "updated to commit $commit"
        }
    }
    if ($ahead -gt 0) {
        Write-Warn "Your checkout has $ahead commit(s) that are not on GitHub's main branch."
    }
}

$pyproject = Get-Content (Join-Path $RepoRoot "pyproject.toml") -Raw
if ($pyproject -notmatch '(?m)^version = "([^"]+)"') {
    Stop-WithError "Could not read the version from pyproject.toml." "Make sure pyproject.toml has a line like: version = ""0.1.0"""
}
$Version = $Matches[1]
Write-Ok "version $Version, commit $commit, working tree clean"

# 4. Build
Write-Step "Building $Image (this can take a few minutes the first time)"
Set-Content -Path $LogFile -Value ("MidiMCP publish log {0:u}  image {1}  version {2}  commit {3}" -f (Get-Date), $Image, $Version, $commit)
Write-Info "full build output is also saved to $LogFile"
$buildArgs = @(
    "build", "--pull", "--progress=plain", "--platform", "linux/amd64",
    "-t", "${Image}:$Version", "-t", "${Image}:$commit", "-t", "${Image}:latest", "."
)
if ((Invoke-Native "docker" $buildArgs $LogFile) -ne 0) {
    Stop-WithError "docker build failed (see the red lines above, or $LogFile)." "Check your internet connection and that Docker Desktop has enough disk space, then run this again."
}
$size = (Get-NativeOutput "docker" @("image", "inspect", "${Image}:latest", "--format", "{{.Size}}")).Text
if ($size -match "^\d+$") { Write-Info ("image size {0:N0} MB" -f ([double]$size / 1MB)) }
Write-Ok "built ${Image}:$Version, :$commit and :latest"

if ($NoPush) {
    Write-Banner "Build finished (not pushed: -NoPush)"
    exit 0
}

# 5. Login
Write-Step "Logging in to ghcr.io as $Owner"
$token = $env:GHCR_TOKEN
if (-not $token) {
    Write-Info "Needs a GitHub personal access token (classic) with the 'write:packages' scope."
    Write-Info "Create one at https://github.com/settings/tokens/new?scopes=write:packages"
    $secure = Read-Host "  Paste token (input hidden)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
if ($token) { $token = $token.Trim() }
if (-not $token) { Stop-WithError "No token received (the paste did not arrive)." "Run again and paste with Ctrl+V or right-click; the image is already built, so the rerun is quick." }
Write-Info ("token received ({0} characters)" -f $token.Length)

$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$loginOutput = ($token | & docker login ghcr.io -u $Owner --password-stdin 2>&1 | ForEach-Object { "$_" }) -join "`n"
$loginCode = $LASTEXITCODE
$ErrorActionPreference = $previous
$token = $null
if ($loginCode -ne 0) {
    Write-Host "    $loginOutput" -ForegroundColor Red
    Stop-WithError "Login to ghcr.io failed." "Check the token is not expired and has the 'write:packages' scope, and that '$Owner' is your GitHub username."
}
Write-Ok "logged in"

try {
    # 6. Push
    Write-Step "Pushing to ghcr.io"
    foreach ($tag in @($Version, $commit, "latest")) {
        Write-Info "pushing ${Image}:$tag"
        if ((Invoke-Native "docker" @("push", "${Image}:$tag") $LogFile) -ne 0) {
            Stop-WithError "Push of ${Image}:$tag failed." "If it says 'denied', the token lacks write:packages or the package belongs to another account."
        }
    }
    Write-Ok "pushed 3 tags"
} finally {
    # 7. Logout
    Write-Step "Logging out of ghcr.io"
    $null = Get-NativeOutput "docker" @("logout", "ghcr.io")
    Write-Ok "credentials removed from Docker"
}

$total = ((Get-Date) - $script:Started).TotalMinutes
Write-Banner ("Published {0}:latest  (version {1}, commit {2})  in {3:N1} min" -f $Image, $Version, $commit, $total)
Write-Host ""
Write-Host "  First time only: make the package public so TrueNAS can pull it:" -ForegroundColor Yellow
Write-Host "    https://github.com/users/$Owner/packages/container/midimcp/settings" -ForegroundColor Yellow
Write-Host "    -> Danger Zone -> Change visibility -> Public" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Then on TrueNAS: Apps -> midimcp -> Update (or install with docs\deploy\truenas-app.yaml)." -ForegroundColor Green
Write-Host ""
exit 0
