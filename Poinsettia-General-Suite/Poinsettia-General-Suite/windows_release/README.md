# Poinsettia Windows Release

This directory is an isolated Windows desktop release package. It does not
modify the existing Flask website. At launch, the package copies the website's
compiled `main.pyc` and `db.pyc`, templates, and static assets into a separate
per-user Windows data directory and runs that copy locally inside a full-screen
iframe.
The original website files and database remain untouched.

## What is included

- The exact website UI running locally in a `pywebview` desktop window.
- A tamper-evident, versioned local EULA clickwrap gate.
- Poinsettia 2, Poinsettia 3.9, and immediately available Poinsettia 4.0 local Ollama
  model bootstrap.
- First-run Ollama/model download progress.
- A Windows RAM pre-check with a Poinsettia 3.9 performance warning below 16 GB.
- English and Spanish UI strings.
- Separate legal and third-party attribution files.
- Frontend minification, Python obfuscation, and sourceless Python packaging build steps.
- A build-time website mirror under the packaged `site_runtime` directory.
- A per-user Inno Setup installer with Start Menu/Desktop shortcuts and
  post-install launch. This signed installer is the recommended public Windows
  distribution; the root ZIP launcher is a development fallback.
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

The local consent record is HMAC-protected and its key is protected with Windows
DPAPI where available. This prevents casual edits to a plain-text acceptance
flag. The release does not ship readable website Python source; the mirrored
backend is compiled to sourceless bytecode and the PyInstaller output is
checked for stray `.py` files. No local desktop application can make its own
executable fully resistant to a user who controls the machine, and browser
JavaScript remains inspectable, so code signing, MSIX packaging, and store
distribution remain part of the release process.