[CmdletBinding()]
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvRoot = Join-Path $ProjectRoot ".poinsettia-venv"
$DataRoot = Join-Path $env:LOCALAPPDATA "Poinsettia\Bootstrap"
$PythonInstallerUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
$OllamaInstallerUrl = "https://ollama.com/download/OllamaSetup.exe"
$SiteUrl = "http://127.0.0.1:5000"

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null

function Find-Python {
    $candidates = @()
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += @{ Path = $py.Source; Prefix = @("-3.11") }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += @{ Path = $python.Source; Prefix = @() }
    }
    $candidates += @(
        @{ Path = (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"); Prefix = @() },
        @{ Path = (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"); Prefix = @() },
        @{ Path = (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"); Prefix = @() }
    )

    foreach ($candidate in $candidates) {
        if (!(Test-Path $candidate.Path)) {
            continue
        }
        # The current Python install manager writes "no runtime installed" to
        # stderr when py.exe exists but Python 3.11 has not been installed.
        # Treat that as a failed candidate and continue to the installer
        # fallback instead of letting PowerShell's Stop preference abort.
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "SilentlyContinue"
            & $candidate.Path @($candidate.Prefix) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
            $candidateExitCode = $LASTEXITCODE
        } catch {
            $candidateExitCode = 1
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($candidateExitCode -eq 0) {
            return $candidate
        }
    }
    return $null
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments
    )
    & $Python.Path @($Python.Prefix) @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

function Install-Python {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "Python was not found. Installing Python 3.11 with winget..."
        & $winget.Source install --id Python.Python.3.11 --exact --scope user `
            --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) {
            Start-Sleep -Seconds 3
            $installed = Find-Python
            if ($installed) {
                return $installed
            }
        }
    }

    Write-Host "Downloading the official Python installer..."
    $installer = Join-Path $DataRoot "python-3.11.9-amd64.exe"
    if (!(Test-Path $installer)) {
        Invoke-WebRequest -Uri $PythonInstallerUrl -OutFile $installer
    }
    $process = Start-Process -FilePath $installer -ArgumentList @(
        "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0"
    ) -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "The Python installer failed with exit code $($process.ExitCode)."
    }
    Start-Sleep -Seconds 3
    $installed = Find-Python
    if (!$installed) {
        throw "Python was installed, but a usable Python 3.11+ interpreter was not found."
    }
    return $installed
}

function Find-Ollama {
    $command = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Test-Ollama {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
}

function Wait-ForOllama {
    param([int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Ollama) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Ollama did not become available on http://127.0.0.1:11434."
}

function Ensure-Ollama {
    $ollama = Find-Ollama
    if (!$ollama) {
        Write-Host "Ollama was not found. Downloading the official installer..."
        $installer = Join-Path $DataRoot "OllamaSetup.exe"
        if (!(Test-Path $installer)) {
            Invoke-WebRequest -Uri $OllamaInstallerUrl -OutFile $installer
        }
        $process = Start-Process -FilePath $installer -ArgumentList "/S" -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "The Ollama installer failed with exit code $($process.ExitCode)."
        }
        Start-Sleep -Seconds 3
        $ollama = Find-Ollama
    }
    if (!$ollama) {
        throw "Ollama was installed, but ollama.exe was not found."
    }

    if (!(Test-Ollama)) {
        Write-Host "Starting Ollama..."
        Start-Process -FilePath $ollama -ArgumentList "serve" `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $DataRoot "ollama.log") `
            -RedirectStandardError (Join-Path $DataRoot "ollama-error.log") | Out-Null
        Wait-ForOllama
    }
    return $ollama
}

function Invoke-Ollama {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Ollama command failed: ollama $($Arguments -join ' ')"
    }
}

function Prepare-Models {
    param([string]$Ollama)

    $models = @(
        @{ Base = "llama3.2:3b"; Name = "poinsettia"; File = "Modelfile" },
        @{ Base = "gemma4:12b"; Name = "p3"; File = "modelfile3" },
        @{ Base = "gemma4:26b"; Name = "p4-fax"; File = "modelfile4-fax" },
        @{ Base = "gemma4:31b"; Name = "p4-candor"; File = "modelfile4-candor" }
    )

    foreach ($model in $models) {
        Write-Host "Preparing base model $($model.Base)..."
        Invoke-Ollama -Executable $Ollama -Arguments @("pull", $model.Base)
        Write-Host "Creating $($model.Name)..."
        Invoke-Ollama -Executable $Ollama -Arguments @(
            "create", $model.Name, "-f", (Join-Path $ProjectRoot $model.File)
        )
    }
}

$python = Find-Python
if (!$python) {
    $python = Install-Python
}

$venvPython = Join-Path $VenvRoot "Scripts\python.exe"
if (!(Test-Path $venvPython)) {
    Write-Host "Creating the Poinsettia Python environment..."
    Invoke-Python -Python $python -Arguments @("-m", "venv", $VenvRoot)
}

Write-Host "Installing Python requirements..."
& $venvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Could not upgrade pip."
}
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the Poinsettia requirements."
}

$ollama = Ensure-Ollama
Prepare-Models -Ollama $ollama

$existingSite = Test-NetConnection -ComputerName "127.0.0.1" -Port 5000 `
    -InformationLevel Quiet -WarningAction SilentlyContinue
if ($existingSite) {
    Write-Host "Poinsettia is already running on $SiteUrl."
    if (!$NoBrowser) {
        Start-Process $SiteUrl
    }
    exit 0
}

$stdout = Join-Path $DataRoot "poinsettia.log"
$stderr = Join-Path $DataRoot "poinsettia-error.log"
Write-Host "Starting Poinsettia..."
$siteProcess = Start-Process -FilePath $venvPython `
    -ArgumentList @("main.py") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

try {
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Seconds 2
        $ready = Test-NetConnection -ComputerName "127.0.0.1" -Port 5000 `
            -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($siteProcess.HasExited -and !$ready) {
            throw "Poinsettia stopped during startup. See $stderr."
        }
    } while (!$ready -and (Get-Date) -lt $deadline)

    if (!$ready) {
        throw "Poinsettia did not open port 5000 within 60 seconds. See $stderr."
    }

    Write-Host "Poinsettia is ready at $SiteUrl"
    if (!$NoBrowser) {
        Start-Process $SiteUrl
    }
    Write-Host "Leave this window open while using Poinsettia. Press Ctrl+C to stop it."
    Wait-Process -Id $siteProcess.Id
} finally {
    if (!$siteProcess.HasExited) {
        Stop-Process -Id $siteProcess.Id -Force
    }
}