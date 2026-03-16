param(
    [string]$RepoOwner = "Shinnken",
    [string]$RepoName = "pepper-WoZ",
    [string]$Branch = "pepper-WoZ-UI-demo",
    [string]$CloneParent = "$env:USERPROFILE\Documents\PepperDemo"
)

$ErrorActionPreference = "Stop"

function Ensure-Winget {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is required but was not found. Install App Installer from Microsoft Store and run this script again."
    }
}

function Install-PackageIfMissing {
    param(
        [Parameter(Mandatory = $true)][string]$CheckCommand,
        [Parameter(Mandatory = $true)][string]$WingetId,
        [Parameter(Mandatory = $true)][string]$DisplayName
    )

    if (Get-Command $CheckCommand -ErrorAction SilentlyContinue) {
        Write-Host "$DisplayName already installed."
        return
    }

    Write-Host "Installing $DisplayName..."
    winget install --id $WingetId --exact --source winget --accept-package-agreements --accept-source-agreements --silent
}

function Resolve-Python312 {
    $candidates = @(
        "py -3.12",
        "python3.12",
        "python"
    )

    foreach ($candidate in $candidates) {
        try {
            $versionOutput = & cmd /c "$candidate --version" 2>&1
            if ($LASTEXITCODE -ne 0) {
                continue
            }
            if ($versionOutput -match "Python 3\.12") {
                return $candidate
            }
        }
        catch {
        }
    }

    throw "Python 3.12 was not detected after installation. Restart terminal and rerun script."
}

function Ensure-Python312Installed {
    try {
        $python = Resolve-Python312
        Write-Host "Python 3.12 detected ($python)."
        return $python
    }
    catch {
        Write-Host "Python 3.12 not found. Installing Python 3.12..."
        winget install --id "Python.Python.3.12" --exact --source winget --accept-package-agreements --accept-source-agreements --silent
        return Resolve-Python312
    }
}

function Ensure-Clone {
    param(
        [Parameter(Mandatory = $true)][string]$Owner,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$TargetBranch,
        [Parameter(Mandatory = $true)][string]$ParentDir
    )

    if (-not (Test-Path $ParentDir)) {
        New-Item -ItemType Directory -Path $ParentDir | Out-Null
    }

    $repoDir = Join-Path $ParentDir $Name
    $repoUrl = "https://github.com/$Owner/$Name.git"

    if (Test-Path $repoDir) {
        Write-Host "Repository already exists at $repoDir"
        Push-Location $repoDir
        try {
            git fetch origin $TargetBranch
            git checkout $TargetBranch
            git pull --ff-only origin $TargetBranch
        }
        finally {
            Pop-Location
        }
    }
    else {
        Push-Location $ParentDir
        try {
            git clone --branch $TargetBranch --single-branch $repoUrl
        }
        finally {
            Pop-Location
        }
    }

    return $repoDir
}

function New-DesktopShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$TargetBat,
        [Parameter(Mandatory = $true)][string]$WorkingDir,
        [Parameter(Mandatory = $true)][string]$ShortcutName
    )

    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "$ShortcutName.lnk"

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetBat
    $shortcut.WorkingDirectory = $WorkingDir
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
    $shortcut.Save()

    Write-Host "Desktop shortcut created: $shortcutPath"
}

Ensure-Winget
Install-PackageIfMissing -CheckCommand "git" -WingetId "Git.Git" -DisplayName "Git"
$pythonCmd = Ensure-Python312Installed
$repoPath = Ensure-Clone -Owner $RepoOwner -Name $RepoName -TargetBranch $Branch -ParentDir $CloneParent

$venvPath = Join-Path $repoPath ".venv"
$pepperAppDir = Join-Path $repoPath "PepperApp"
$requirementsPath = Join-Path $pepperAppDir "requirements.txt"
$runBatPath = Join-Path $repoPath "run_pepper_app_venv.bat"

if (-not (Test-Path $requirementsPath)) {
    throw "requirements.txt not found at: $requirementsPath"
}

Write-Host "Creating virtual environment at $venvPath"
& cmd /c "$pythonCmd -m venv \"$venvPath\""

$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Venv python not found at: $venvPython"
}

Write-Host "Installing dependencies from $requirementsPath"
& "$venvPython" -m pip install --upgrade pip
& "$venvPython" -m pip install -r "$requirementsPath"

if (-not (Test-Path $runBatPath)) {
    $batContent = @"
@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "APP_PY=%SCRIPT_DIR%PepperApp\pepper_app.py"

if not exist "%VENV_PY%" (
    echo Virtual environment Python not found: "%VENV_PY%"
    pause
    exit /b 1
)

if not exist "%APP_PY%" (
    echo App file not found: "%APP_PY%"
    pause
    exit /b 1
)

pushd "%SCRIPT_DIR%PepperApp"
"%VENV_PY%" "%APP_PY%"
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo Application exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
"@
    Set-Content -Path $runBatPath -Value $batContent -Encoding ASCII
}

New-DesktopShortcut -TargetBat $runBatPath -WorkingDir $pepperAppDir -ShortcutName "Pepper UI Demo"

Write-Host ""
Write-Host "Setup complete. Use the 'Pepper UI Demo' desktop shortcut to launch the app."
