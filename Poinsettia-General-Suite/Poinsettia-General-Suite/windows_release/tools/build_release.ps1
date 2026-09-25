param(
    [ValidateSet("x86", "x64", "arm64")]
    [string]$Architecture = "x64",
    [string]$PackageVersion = "4.0.0.0",
    [string]$StoreIdentityName = $env:POINSETTIA_STORE_IDENTITY_NAME,
    [string]$StorePublisher = $env:POINSETTIA_STORE_PUBLISHER,
    [string]$OllamaInstallerUrl = $env:POINSETTIA_OLLAMA_INSTALLER_URL,
    [string]$OllamaSha256 = $env:POINSETTIA_OLLAMA_SHA256,
    [string]$SigningCertificateThumbprint = $env:POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT,
    [string]$TimestampUrl = $env:POINSETTIA_TIMESTAMP_URL,
    [switch]$CreateMsix,
    [switch]$CreateInstaller,
    [switch]$RequireSignature
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python = Join-Path $Root ".venv-windows\Scripts\python.exe"
if (!$TimestampUrl) {
    $TimestampUrl = "http://timestamp.digicert.com"
}

function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path $kitsRoot) {
        $candidate = Get-ChildItem $kitsRoot -Recurse -File -Filter "signtool.exe" |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }
    return $null
}

function Sign-ReleaseFile {
    param([string]$Path)

    $signTool = Find-SignTool
    if (!$signTool) {
        throw "signtool.exe was not found. Install the Windows SDK before signing a release."
    }
    & $signTool sign `
        /sha1 $SigningCertificateThumbprint `
        /fd SHA256 `
        /tr $TimestampUrl `
        /td SHA256 `
        $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed for $Path."
    }
}

if (!(Test-Path $Python)) {
    throw "Create .venv-windows and install windows_release\requirements.txt first."
}

if ($RequireSignature -and !$SigningCertificateThumbprint) {
    throw "Set POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT before using -RequireSignature."
}

if ($CreateInstaller) {
    if (!$OllamaSha256 -or $OllamaSha256 -notmatch "^[0-9a-fA-F]{64}$") {
        throw "Set POINSETTIA_OLLAMA_SHA256 to the approved 64-character digest before creating a public installer."
    }
    if (!$OllamaInstallerUrl -or $OllamaInstallerUrl -notmatch "^https://" -or $OllamaInstallerUrl -match "/download/OllamaSetup\.exe/?$") {
        throw "Set POINSETTIA_OLLAMA_INSTALLER_URL to a pinned HTTPS Ollama installer URL before creating a public installer."
    }
}

& $Python "$PSScriptRoot\minify.py"
& $Python "$PSScriptRoot\obfuscate.py"

$Dist = Join-Path $Root "windows_release\build\app"
if (Test-Path $Dist) { Remove-Item $Dist -Recurse -Force }
New-Item -ItemType Directory -Path $Dist | Out-Null
Copy-Item "$Root\windows_release\dist" "$Dist\dist" -Recurse
Copy-Item "$Root\windows_release\legal" "$Dist\legal" -Recurse
Copy-Item "$Root\windows_release\models" "$Dist\models" -Recurse
Copy-Item "$Root\windows_release\open_source_credits.txt" "$Dist\open_source_credits.txt"
$OllamaPin = @{
    url = $OllamaInstallerUrl
    sha256 = $OllamaSha256.ToLowerInvariant()
} | ConvertTo-Json
Set-Content -Path (Join-Path $Dist "ollama_pin.json") -Value $OllamaPin -Encoding UTF8
$SiteRuntime = Join-Path $Dist "site_runtime"
New-Item -ItemType Directory -Path $SiteRuntime | Out-Null
& $Python "$PSScriptRoot\compile_site.py" `
    --source-root $Root `
    --destination $SiteRuntime
Copy-Item "$Root\templates" "$SiteRuntime\templates" -Recurse
Copy-Item "$Root\static" "$SiteRuntime\static" -Recurse

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name PoinsettiaWindows `
    --paths "$Root\windows_release\build\obfuscated" `
    --add-data "$Dist\dist;dist" `
    --add-data "$Dist\legal;legal" `
    --add-data "$Dist\models;models" `
    --add-data "$Dist\open_source_credits.txt;." `
    --add-data "$Dist\ollama_pin.json;." `
    --add-data "$Dist\site_runtime;site_runtime" `
    "$Root\windows_release\build\obfuscated\run_windows.py"

$PyInstallerOutput = Join-Path $Root "dist\PoinsettiaWindows"
$ReadablePython = Get-ChildItem $PyInstallerOutput -Recurse -File -Filter "*.py"
if ($ReadablePython) {
    $paths = ($ReadablePython | ForEach-Object { $_.FullName }) -join "`n"
    throw "Release output contains readable Python source files:`n$paths"
}

Write-Host "PyInstaller output is in $Root\dist\PoinsettiaWindows"

$MainExecutable = Join-Path $PyInstallerOutput "PoinsettiaWindows.exe"
if ($SigningCertificateThumbprint) {
    Sign-ReleaseFile -Path $MainExecutable
} elseif ($RequireSignature) {
    throw "The PyInstaller application was not signed."
} else {
    Write-Warning "The PyInstaller application is unsigned. Smart App Control may block public downloads."
}

$MsixRoot = Join-Path $Root "windows_release\build\msix"
if (Test-Path $MsixRoot) { Remove-Item $MsixRoot -Recurse -Force }
New-Item -ItemType Directory -Path $MsixRoot | Out-Null
Copy-Item "$PyInstallerOutput\*" $MsixRoot -Recurse

$Assets = Join-Path $MsixRoot "Assets"
New-Item -ItemType Directory -Path $Assets | Out-Null
$Logo = Join-Path $Root "static\poinsettia-logo.png"
if (!(Test-Path $Logo)) {
    $Logo = Join-Path $Root "static\favicon.png"
}
if (!(Test-Path $Logo)) {
    throw "A PNG app logo is required at static\poinsettia-logo.png or static\favicon.png."
}
foreach ($AssetName in @(
    "StoreLogo.png",
    "Square44x44Logo.png",
    "Square71x71Logo.png",
    "Square150x150Logo.png",
    "Square310x310Logo.png"
)) {
    Copy-Item $Logo (Join-Path $Assets $AssetName)
}

$ManifestTemplate = Join-Path $PSScriptRoot "..\msix\AppxManifest.xml.in"
$ManifestPath = Join-Path $MsixRoot "AppxManifest.xml"
if (!(Test-Path $ManifestTemplate)) {
    throw "MSIX manifest template was not found at $ManifestTemplate."
}

if ($CreateMsix -and (
    !$StoreIdentityName -or !$StorePublisher -or
    $StoreIdentityName.Contains("REPLACE") -or $StorePublisher.Contains("REPLACE")
)) {
    throw "Set POINSETTIA_STORE_IDENTITY_NAME and POINSETTIA_STORE_PUBLISHER before using -CreateMsix."
}

$Manifest = Get-Content $ManifestTemplate -Raw
if ($StoreIdentityName) {
    $Manifest = $Manifest.Replace(
        "__IDENTITY_NAME__",
        [System.Security.SecurityElement]::Escape($StoreIdentityName)
    )
}
if ($StorePublisher) {
    $Manifest = $Manifest.Replace(
        "__PUBLISHER__",
        [System.Security.SecurityElement]::Escape($StorePublisher)
    )
}
$Manifest = $Manifest.Replace("__VERSION__", $PackageVersion)
$Manifest = $Manifest.Replace("__ARCHITECTURE__", $Architecture)
Set-Content -Path $ManifestPath -Value $Manifest -Encoding UTF8

Write-Host "MSIX staging directory is in $MsixRoot"

if ($CreateMsix) {
    $MakeAppxCommand = Get-Command makeappx.exe -ErrorAction SilentlyContinue
    if (!$MakeAppxCommand) {
        throw "makeappx.exe was not found. Install the Windows SDK before using -CreateMsix."
    }
    $OutputPackage = Join-Path $Root "windows_release\build\Poinsettia-$PackageVersion-$Architecture.msix"
    if (Test-Path $OutputPackage) { Remove-Item $OutputPackage -Force }
    & $MakeAppxCommand.Source pack /d $MsixRoot /p $OutputPackage /o
    if ($LASTEXITCODE -ne 0) {
        throw "makeappx.exe failed with exit code $LASTEXITCODE."
    }
    Write-Host "MSIX package is in $OutputPackage"
}

if ($CreateInstaller) {
    if ($Architecture -ne "x64") {
        throw "The Inno Setup installer currently supports the x64 PyInstaller build only."
    }
    $InnoCandidates = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    $InnoCompiler = $InnoCandidates | Select-Object -First 1
    if (!$InnoCompiler) {
        throw "ISCC.exe was not found. Install Inno Setup 6 before using -CreateInstaller."
    }

    $InstallerScript = Join-Path $PSScriptRoot "..\installer\Poinsettia.iss"
    $InstallerOutput = Join-Path $Root "windows_release\build\installer"
    if (Test-Path $InstallerOutput) { Remove-Item $InstallerOutput -Recurse -Force }
    New-Item -ItemType Directory -Path $InstallerOutput | Out-Null
    & $InnoCompiler `
        "/DAppVersion=$PackageVersion" `
        "/DSourceDir=$PyInstallerOutput" `
        "/DOutputDir=$InstallerOutput" `
        $InstallerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE."
    }
    $InstallerExecutable = Get-ChildItem $InstallerOutput -File -Filter "*.exe" |
        Select-Object -First 1
    if (!$InstallerExecutable) {
        throw "Inno Setup did not produce an installer executable."
    }
    if ($SigningCertificateThumbprint) {
        Sign-ReleaseFile -Path $InstallerExecutable.FullName
    } elseif ($RequireSignature) {
        throw "The Windows installer was not signed."
    } else {
        Write-Warning "The Windows installer is unsigned. Smart App Control may block public downloads."
    }
    Write-Host "Windows installer is in $InstallerOutput"
}