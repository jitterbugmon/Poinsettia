# GitHub release workflow

GitHub Releases are now the primary distribution path for the Windows
application. Microsoft Store packaging is retained only as an optional future
path and is not required for normal downloads.

## What customers receive

`Poinsettia-<version>-Windows-x64-Setup.exe` is a per-user installer. It:

- Does not require administrator access.
- Installs under the user's local application programs directory.
- Creates a Start Menu shortcut.
- Offers an optional Desktop shortcut.
- Launches Poinsettia automatically after installation.
- Leaves the user's local conversations and files in place if the app is
  uninstalled.
- Downloads Ollama and the Poinsettia models only after the user accepts the
  local-use agreement.

The installer does not include model weights. This keeps the download smaller;
the Poinsettia base models are downloaded from Ollama after consent and their
Apache License, Version 2.0 attribution is included in the installer.

## Release a version

1. Push the repository to a GitHub repository.
2. Create and push a version tag:

   ```powershell
    git tag v4.0.0
   git push origin v3.9.0
   ```

3. GitHub Actions runs on a Windows runner and:
   - Installs Python dependencies.
   - Builds the PyInstaller application.
   - Compiles the Inno Setup installer.
   - Publishes the installer to a GitHub Release.
4. Download the installer from the generated release and test it on a clean
   Windows profile before sharing the release publicly.

The tagged installer job intentionally fails closed unless the repository has
both `POINSETTIA_OLLAMA_INSTALLER_URL` configured as a repository variable and
`POINSETTIA_OLLAMA_SHA256` configured as a repository secret. The build embeds
those values in the release so the first-run downloader does not fall back to
Ollama's moving latest-download URL.

## Local Windows build

Install Inno Setup 6, prepare the Windows virtual environment, and run:

```powershell
.\windows_release\tools\build_release.ps1 -CreateInstaller
```

The output is written to:

```text
windows_release\build\installer\
```

## Important release checks

- Use a stable, pinned Ollama installer version for a public release instead of
  relying on a moving latest-download URL. Configure its URL as the
  `POINSETTIA_OLLAMA_INSTALLER_URL` repository variable.
- Set `POINSETTIA_OLLAMA_SHA256` to the approved installer digest repository
  secret.
- Keep the Apache License, Version 2.0 attribution for `gemma4:26b` and
  `gemma4:31b` in the release bundle.
- Code-sign both the application executable and installer before publishing if
  you have a Windows code-signing certificate. Smart App Control may block an
  unsigned public download, so the signed installer—not the ZIP—is the
  customer-facing artifact. The build supports a certificate installed in the
  Windows certificate store through
  `POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT`; use `-RequireSignature` for a
  release build so an unsigned installer cannot be published accidentally.
- Test the installer on a clean Windows machine.
- Publish checksums alongside the installer when the release is created.
- Keep the GitHub release description accurate about local AI, web research,
  internet access, microphone use, and first-run model downloads.

The GitHub Actions workflow builds the artifact, but it cannot replace these
release-specific security and compatibility checks.