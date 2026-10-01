# Windows build and GitHub distribution

This procedure builds only the isolated `windows_release` package. It does not
change the current website workflow or its source files.

## 1. Prepare a Windows build machine

1. Install Python 3.11 for Windows and the Windows 10/11 SDK.
2. Install Ollama separately while validating the release, or allow the first
   run bootstrapper to use the official signed installer.
3. Clone the repository and create a clean virtual environment:

```powershell
py -3.11 -m venv .venv-windows
.venv-windows\Scripts\python -m pip install --upgrade pip
.venv-windows\Scripts\python -m pip install -r windows_release\requirements.txt
```

## 2. Validate licenses and models

1. Review `windows_release/open_source_credits.txt`.
2. Distribute the Apache License, Version 2.0 notice for the `gemma4:e4b`
   Gemma 4B base weights with the Poinsettia 2.9 release.
3. Distribute the Apache License, Version 2.0 notice for the `gemma4:12b`
   Gemma 4 12B base weights with the Poinsettia 3.9 model. This is the
   multimodal image and native audio model used by P3.9.
4. Confirm the exact model files and licenses permitted for the intended
   Microsoft Store distribution. Poinsettia 4.0's `gemma4:26b` and
   `gemma4:31b` base models are also Apache License 2.0; keep the attribution
   notice with the release. Do not embed weights in the installer unless
   redistribution is allowed.

## 3. Build the application

From PowerShell:

```powershell
.\windows_release\tools\build_release.ps1
```

The script minifies the frontend, obfuscates the Windows wrapper and website
backend, compiles the backend to sourceless `.pyc` files, and creates a PyInstaller
directory build. At runtime, the copied website is placed in per-user Windows
data and loaded into a full-screen iframe. The build fails if the PyInstaller
output contains readable `.py` files. The release should still be code signed
before testing outside the build machine.

## 4. Test the packaged app

1. Run `dist\PoinsettiaWindows\PoinsettiaWindows.exe` on a clean Windows user
   profile.
2. Confirm the mirrored website opens immediately without a second Windows
   agreement screen.
3. Confirm account signup still requires review and acceptance of the current
   EULA and Privacy Policy.
4. Before account consent, confirm local model setup has not started.
5. After signup, confirm the website's accepted account triggers local model
   setup and Ollama `/api/pull` progress updates the progress indicator.
6. Confirm an existing account with current consent can sign in and trigger
   setup, while an account needing updated consent cannot.
7. Confirm a machine below 16 GB shows the Poinsettia 3.9 warning.
8. Confirm both custom models are created from the release Modelfiles and that
   P3.9 uses `gemma4:12b`.
9. Confirm Poinsettia 4.0 Fax and Candor are available immediately.
10. Confirm the iframe shows the same visual layout as the current website.
11. Confirm the Windows copy writes its own database and `user_files` directory,
   never the repository's database or files.
12. Confirm uninstall leaves no unexpected website or Replit workflow changes.
13. For a production build, set `POINSETTIA_OLLAMA_INSTALLER_URL` to a pinned
    Ollama installer URL and `POINSETTIA_OLLAMA_SHA256` to its approved
    SHA-256 digest. Confirm Authenticode validation succeeds before the
    installer is launched.

## 5. Create the GitHub installer

Install Inno Setup 6, then run:

```powershell
.\windows_release\tools\build_release.ps1 -CreateInstaller
```

The installer is written to:

```text
windows_release\build\installer\
```

It installs per-user, creates a Start Menu shortcut, offers a Desktop
shortcut, and launches Poinsettia after installation. It intentionally does
not remove the user's local conversations or files during uninstall.

For the public release process and GitHub Actions workflow, read
`GITHUB_RELEASE.md`.

## 6. Optional MSIX packaging

The repository retains a parameterized manifest and build staging flow for a
future Store release. From a Windows machine with the Windows SDK installed:

```powershell
$env:POINSETTIA_STORE_IDENTITY_NAME = "the-identity-from-partner-center"
$env:POINSETTIA_STORE_PUBLISHER = "the-publisher-from-partner-center"
.\windows_release\tools\build_release.ps1 -CreateMsix
```

The script first creates a PyInstaller build and an MSIX staging directory. With
`-CreateMsix`, it also invokes `makeappx.exe`:

1. Set the package identity and publisher to the values assigned to the
   reserved Store product.
2. Keep the package version in four-part Windows format, such as `4.0.0.0`.
3. Confirm the generated package contains `PoinsettiaWindows.exe`, all required
   assets, the legal documents, and the mirrored site runtime.
4. Sign and install the package for local testing.
5. Run the Windows App Certification Kit.
6. Test install, update, repair, uninstall, and clean-profile first launch.
7. Submit the Store submission upload container through Partner Center.

The Store package should not include secrets or downloaded model weights unless
their licenses and package size are approved. Large model downloads belong in
the first-run signed bootstrap flow.