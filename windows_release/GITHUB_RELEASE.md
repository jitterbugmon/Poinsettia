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
- Downloads Ollama and the Poinsettia models only after the mirrored website
  confirms that the signed-in account has accepted the current EULA and Privacy
  Policy during signup or re-acceptance.

The installer does not include model weights. This keeps the download smaller;
the Poinsettia base models are downloaded from Ollama after consent and their
Apache License, Version 2.0 attribution is included in the installer.

## Publish a signed release

1. Push the repository to a GitHub repository.
2. Create and push a version tag:

   ```powershell
    git tag v4.0.0
    git push origin v4.0.0
   ```

3. GitHub Actions runs on a Windows runner and:
   - Installs Python dependencies.
   - Builds the PyInstaller application.
   - Signs and verifies the application executable.
   - Compiles the Inno Setup installer.
   - Signs and verifies the installer, then validates its signature again before
     uploading or publishing.
   - Publishes the installer to a GitHub Release.
4. Download the installer from the generated release and test it on a clean
   Windows profile before sharing the release publicly.

All installer builds, including unsigned beta builds, require
`POINSETTIA_OLLAMA_INSTALLER_URL` as a repository variable and
`POINSETTIA_OLLAMA_SHA256` as a repository secret. Use an approved, pinned
HTTPS Ollama installer URL and its approved 64-character SHA-256 digest. The
build embeds these values so the first-run downloader does not fall back to
Ollama's moving latest-download URL.

Tagged builds always require a signature, regardless of workflow input. The
`signed` manual mode also requires a signature. Both need
`POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT` as a repository variable and a
trusted CA-issued Windows code-signing certificate with its private key
available to the Windows signing environment. The thumbprint identifies a
certificate; it does not provision the certificate or private key. A standard
hosted GitHub runner does not have this project's certificate installed, so a
trusted certificate and suitable Windows signing infrastructure must be
arranged before tagged or signed manual builds can succeed. No certificate
provisioning or hosted-runner signing integration is included here. Do not use a
self-signed certificate for signed releases.

## Build an unsigned beta artifact for testing

For a manual test build, go to **Actions → Build Windows release → Run
workflow**, select a branch, and leave **Installer mode** at its default
`unsigned-beta` choice. The job clears the signing thumbprint only for this
intentional branch/manual unsigned-beta build, so it does not need a signing
certificate even when the repository variable is configured. It creates an
unsigned installer and `SHA256SUMS.txt`, then uploads them in an artifact named
`poinsettia-windows-installer-unsigned-beta`. Download and unzip that workflow
artifact to obtain the installer and checksum file. A manual run never creates
a GitHub Release. Selecting `signed` instead requires the signing certificate,
and the workflow verifies the application and installer signatures.

Before sharing an unsigned beta, obtain explicit owner approval, clearly
disclose that it is unsigned and a beta, verify the downloaded executable
against the accompanying SHA-256 checksum, and test it on a clean Windows
machine/profile. The checksum helps detect accidental corruption; it is not a
signature or proof of publisher identity. Do not represent an unsigned beta as
a signed/public release or tell users to disable Windows protections or choose
“Run anyway.” Unsigned builds are not claimed to avoid SmartScreen or Smart App
Control.

## Local Windows build

Install Inno Setup 6, prepare the Windows virtual environment, and run:

```powershell
$env:POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT = ""
.\windows_release\tools\build_release.ps1 -CreateInstaller
```

Clearing the thumbprint explicitly makes this an unsigned local development/test
build. A trusted certificate is not needed. The installer bundles the
application's Python runtime through the PyInstaller build; end users do not
need to install Python separately. Local build prerequisites still include the
pinned Ollama URL and SHA-256 digest described above.

The output is written to:

```text
windows_release\build\installer\
```

To sign locally, install a trusted CA-issued code-signing certificate and
private key in the Windows certificate store, set
`POINSETTIA_SIGNING_CERTIFICATE_THUMBPRINT`, and pass `-RequireSignature`. The
builder refuses to continue if it cannot sign and verify the expected
certificate. This workspace is Linux and has not produced an executable;
running the Windows build and testing its installer on Windows are still
required.

## Important release checks

- Use a stable, pinned Ollama installer version for a public release instead of
  relying on a moving latest-download URL. Configure its URL as the
  `POINSETTIA_OLLAMA_INSTALLER_URL` repository variable.
- Set `POINSETTIA_OLLAMA_SHA256` to the approved installer digest repository
  secret.
- Keep the Apache License, Version 2.0 attribution for `gemma4:26b` and
  `gemma4:31b` in the release bundle.
- Tagged CI releases and manual `signed` builds require valid Authenticode
  signatures on the main application executable and outer installer. Both
  signatures are checked against the configured signer thumbprint; CI checks
  the installer again before artifact upload and (for pushed tags) release
  publication. Manual builds, including manual dispatches on a tag, never
  automatically publish a GitHub Release.
- Manual branch builds default to the unsigned-beta path. Keep those artifacts
  private to testing unless an owner explicitly approves a clearly disclosed
  beta distribution after checksum and clean-Windows testing.
- This verification does not establish SmartScreen reputation or guarantee
  that Smart App Control will allow execution. Code signing is not a promise to
  bypass either Windows protection.
- The current build does not separately sign or verify every bundled native
  executable/DLL, nor does it configure or verify Authenticode signing for the
  Inno-generated uninstaller. Audit these native dependencies and the installed
  uninstaller on Windows before broad public distribution; add appropriate
  signing and verification if required by the supported Windows policies.
  Installer signature verification is mandatory and does not replace that
  installed-artifact audit.
- Test the installer on a clean Windows machine.
- Publish checksums alongside the installer when the release is created.
- Keep the GitHub release description accurate about local AI, web research,
  internet access, microphone use, and first-run model downloads.

The GitHub Actions workflow builds the artifact, but it cannot replace these
release-specific security and compatibility checks.