# Poinsettia Windows Release

This directory is an isolated Windows desktop release package. It does not
modify the existing Flask website. At launch, the package copies the website's
compiled `main.pyc` and `db.pyc`, templates, and static assets into a separate
per-user Windows data directory and runs that copy locally inside a full-screen
iframe.
The original website files and database remain untouched.

## What is included

- The exact website UI running locally in a `pywebview` desktop window.
- The existing website account and consent flow, without a second Windows
  startup agreement screen.
- Poinsettia 2, Poinsettia 3.9, and immediately available Poinsettia 4.0 local Ollama
  model bootstrap.
- First-run Ollama/model download progress.
- A Windows RAM pre-check with a Poinsettia 3.9 performance warning below 16 GB.
- English and Spanish UI strings.
- Separate legal and third-party attribution files.
- Frontend minification, Python obfuscation, and sourceless Python packaging build steps.
- A build-time website mirror under the packaged `site_runtime` directory.
- A per-user Inno Setup installer with Start Menu/Desktop shortcuts and
  post-install launch. Manual branch builds can create an unsigned beta
  artifact; tagged releases and manual signed builds require verified
  Authenticode signatures. See `GITHUB_RELEASE.md` for the build paths,
  distribution restrictions, and signing infrastructure. The root ZIP launcher
  is a development fallback.
- An optional MSIX manifest template and `makeappx.exe` packaging stage.

## Development run

From the repository root on Windows:

```powershell
py -3.11 -m venv .venv-windows
.venv-windows\Scripts\python -m pip install -r windows_release\requirements.txt
.venv-windows\Scripts\python windows_release\run_windows.py
```

Read `GITHUB_RELEASE.md` before producing a public installer. The existing
website remains the source of truth for the current web release; this package
mirrors it at build time and is intentionally not wired into its workflow.

For the Store-specific gap analysis and remaining certification work, read
`STORE_READINESS.md`.

## Security boundary

The Windows wrapper records local bootstrap authorization only after the
mirrored website confirms a signed-in account has current EULA and Privacy
Policy consent. The local record is HMAC-protected and its key is protected
with Windows DPAPI where available. The release does not ship readable website
Python source; the mirrored backend is compiled to sourceless bytecode and the
PyInstaller output is checked for stray `.py` files. No local desktop
application can make its own executable fully resistant to a user who controls
the machine, and browser JavaScript remains inspectable, so code signing, MSIX
packaging, and store distribution remain part of the release process.

The unsigned-beta path is only for carefully disclosed testing; it is not a
signed release and is not claimed to avoid SmartScreen or Smart App Control.
Obtain explicit owner approval, verify the provided SHA-256 checksum, and test
on a clean Windows machine before any beta distribution. The installer bundles
the Python runtime, so end users do not need a separate Python installation.

Signed builds verify signatures on the main application and outer installer.
The build does not currently sign/verify every bundled native dependency or the
generated uninstaller; see `GITHUB_RELEASE.md` for the required Windows release
audit. A valid signature does not guarantee SmartScreen reputation or Smart
App Control approval.