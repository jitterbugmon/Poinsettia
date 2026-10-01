# Windows unsigned beta: source upload and build

## What this ZIP is

This is a code-only build-source ZIP, not an installer. It includes the existing
batch/PowerShell launcher unchanged and the source for the Windows installer.
It excludes the workspace database, user files, attachments, environment
configuration, Git history, agent memory, caches, and previous release archives.
`SOURCE_SHA256SUMS.txt` records each included source file's SHA-256.

No Setup.exe has been built or tested as part of this handoff. Linux source
checks do not establish Windows compatibility or Smart App Control acceptance.

## Upload source yourself

1. Extract this ZIP to a new, empty folder. Do not upload the full Repl ZIP.
2. In your existing GitHub repository, create a branch for this test, then copy
   these extracted files to the repository root, preserving all paths,
   especially `.github/workflows/windows-release.yml`. Do not nest them in an
   extra project folder. Use a Git client if browser upload omits hidden folders.
3. Commit and push that branch, without creating or pushing a version tag.
   Uploading the ZIP as a single file will not install the workflow.
4. Check the resulting branch tree before building. Existing database/user files
   in the repository are NOT removed by overlaying this ZIP. Do not copy them
   into these source paths or the build inputs.

The owner approved using a code-only ZIP while leaving existing public history
untouched. This does not clean potentially sensitive historical files, revoke
downloaded copies, or authorize a history rewrite. Public repository cleanup is
a separate decision. No release or website publication is authorized here.

## Required repository configuration

In GitHub **Settings → Secrets and variables → Actions**, configure:

- Variable `POINSETTIA_OLLAMA_INSTALLER_URL`: an approved, version-pinned HTTPS
  Ollama Windows installer URL from the official provider, not a moving
  latest-download URL.
- Secret `POINSETTIA_OLLAMA_SHA256`: its independently verified, approved
  64-character SHA-256 digest.

These prerequisites have not been supplied or configured by this handoff.
Do not use a fabricated digest or copy a checksum from an untrusted source.
The build embeds the pin into the application; the digest is an integrity
check, not proof of publisher identity. Do not paste credentials into chat.
No signing certificate or signing thumbprint is needed for this manual
unsigned-beta branch build.

## Produce and retrieve the installer

1. Open **Actions → Build Windows release → Run workflow**.
2. Select your source branch, NOT a tag.
3. Select `installer_mode: unsigned-beta` and run.
4. After success, download the workflow artifact
   `poinsettia-windows-installer-unsigned-beta`.
5. Extract it. Expect `Poinsettia-4.0.0.0-Windows-x64-Setup.exe` and
   `SHA256SUMS.txt`. This manual workflow does not publish a GitHub Release.
6. Return the complete artifact ZIP for inspection, including both files.
   Do not commit Setup.exe or offer public downloads before inspection and
   Windows testing.

On Windows, compare the installer hash with the corresponding line in
`SHA256SUMS.txt`:

```powershell
Get-FileHash .\Poinsettia-4.0.0.0-Windows-x64-Setup.exe -Algorithm SHA256
```

## Clean-Windows test record (still required)

Use a clean Windows machine/profile with Smart App Control enabled. A hosted
build runner or a Linux check is not a substitute for this test.

Record Windows version, Smart App Control state, artifact checksum, and results:

- Does Windows allow the downloaded installer to run? If blocked, record the
  message and stop. Do not disable protections, remove download-origin markers
  to evade a block, or choose “Run anyway.”
- Does installation work without administrator access under the current user's
  LocalAppData Programs folder?
- Does the Start Menu shortcut work? Does the optional Desktop shortcut appear
  only when selected?
- Does the app launch after installation and from each selected shortcut?
- Are agreement and consent shown before Ollama/model downloads? Does declining
  prevent bootstrap?
- After acceptance, does the pinned Ollama download pass its checksum check,
  install successfully, and bootstrap the models? Record failures and blocks.
- Does the installed app start again, use isolated per-user data, and keep the
  user's conversations/files after uninstall?
- Inspect the installed payload and uninstaller for unexpected databases,
  existing user files, secrets, or unrelated workspace content.

Record blocked stages as blocked/not tested, not as passed. The installer is
unsigned beta software. Neither SHA-256 verification nor successful testing
provides signing, publisher-identity, SmartScreen-reputation, or security
guarantees. Public distribution requires a separate explicit approval.