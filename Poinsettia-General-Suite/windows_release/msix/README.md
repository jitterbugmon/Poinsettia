# MSIX packaging scaffold

This directory contains the Store-facing manifest template. The manifest is
intentionally parameterized because Microsoft assigns the final package
identity and publisher values through Partner Center.

The release build script creates a staging directory under
`windows_release/build/msix` and replaces these values:

- `__IDENTITY_NAME__` — the reserved Store identity name.
- `__PUBLISHER__` — the publisher string associated with the Store identity.
- `__VERSION__` — a four-part package version such as `4.0.0.0`.
- `__ARCHITECTURE__` — normally `x64`; create separate packages for other
  architectures or bundle them as permitted by Microsoft.

The build flow uses the existing square Poinsettia favicon for the square MSIX
tile assets. Replace those generated assets with final Store artwork before
submission if the Store listing requires a different branded treatment.

Run from a Windows machine with the Windows SDK installed:

```powershell
$env:POINSETTIA_STORE_IDENTITY_NAME = "REPLACE_WITH_PARTNER_CENTER_IDENTITY"
$env:POINSETTIA_STORE_PUBLISHER = "CN=REPLACE_WITH_PARTNER_CENTER_PUBLISHER"
.\windows_release\tools\build_release.ps1 -CreateMsix
```

The script requires real Partner Center identity values when `-CreateMsix` is
used. It will not create a deceptively installable package with placeholder
publisher information. The Store submission upload container, listing
metadata, certification results, and final signing remain Partner Center /
Windows-only release steps.