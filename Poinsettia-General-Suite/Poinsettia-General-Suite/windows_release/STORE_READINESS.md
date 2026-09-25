# Microsoft Store readiness review

This is an optional Microsoft Store release-readiness review, not a required
step for the new GitHub distribution path and not a Microsoft certification
decision.
Microsoft makes the final determination through Partner Center and the Windows
App Certification Kit.

Official references:

- [Microsoft Store submission overview](https://learn.microsoft.com/en-us/windows/apps/publish/faq/submit-your-app)
- [MSIX package requirements](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements)
- [MSIX certification process](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-certification-process)
- [Microsoft Store Policies](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies)

## Fixed in the project

- Added a parameterized MSIX manifest at `msix/AppxManifest.xml.in`.
- Added MSIX staging and optional `makeappx.exe` packaging to
  `tools/build_release.ps1`.
- Added temporary-file handling, optional SHA-256 pinning through
  `POINSETTIA_OLLAMA_SHA256`, and Authenticode verification before the
  first-run Ollama installer is executed.
- Declared only the capabilities currently required by the desktop app:
  internet access, microphone access, and full-trust Win32 execution.
- Kept model weights out of the package; models are downloaded after consent.
- Included packaged EULA, Privacy Policy, and third-party model attribution
  documents.
- Kept the Windows release's database and user files in per-user application
  data rather than the repository.

## Still required before submission

### Partner Center

- Create and verify a Microsoft Partner Center developer account.
- Reserve the Poinsettia product name.
- Replace the MSIX identity and publisher placeholders with the values assigned
  to the reserved product.
- Complete the Store listing, category, supported devices, age rating, privacy
  URL, support URL, screenshots, icons, and commercial distribution settings.

### Windows packaging

- Build on Windows with the Windows SDK and PyInstaller.
- Run the build script with the real identity values and `-CreateMsix`.
- Validate the resulting package with the Windows App Certification Kit.
- Test installation, first launch, update, repair, uninstall, and clean-profile
  behavior on every claimed architecture and Windows version.
- Produce the Store submission upload container required by Partner Center.

### Ollama and model bootstrap

- Confirm that the current Ollama installer and its silent-install behavior are
  permitted for the intended Store package.
- Confirm that downloading model weights after installation is acceptable and
  clearly disclosed in the listing and first-run flow.
- Test interrupted downloads, offline startup, insufficient disk space, blocked
  network access, and a missing or incompatible Ollama executable.
- Keep the Apache License, Version 2.0 attribution for the `gemma4:26b` and
  `gemma4:31b` base models with the planned distribution.

### Policy and product review

- Ensure the listing accurately describes local AI, live web research, image
  input, audio input, microphone access, external downloads, and limitations.
- Complete the IARC age-rating questionnaire accurately.
- Review the Microsoft Store requirements for live generative AI content and
  user-generated content.
- Provide a support channel and a way to report harmful or malfunctioning
  generated content.
- Do not ship development secrets, test accounts, repository data, or model
  weights that are not licensed for redistribution.

## Current blocker

This repository can still prepare an MSIX staging tree, but actual package
creation and certification still require a Windows machine with the Windows
SDK, a real Partner Center identity, and the Windows App Certification Kit.
GitHub distribution does not require any of those Store-specific steps.