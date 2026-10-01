"""Export only reviewed Windows build inputs, never the whole workspace."""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
FILES = (
    ".github/workflows/windows-release.yml",
    ".gitignore",
    "main.py",
    "db.py",
    "start_poinsettia.bat",
    "start_poinsettia.ps1",
    "requirements.txt",
    "dependencies.txt",
    "Modelfile",
    "modelfile3",
    "modelfile4-candor",
    "modelfile4-fax",
    "WINDOWS_QUICKSTART.md",
    "WINDOWS_BUILD_HANDOFF.md",
    "static/apache-2.0.txt",
    "static/mit-license.txt",
    "static/favicon.ico",
    "static/favicon.png",
    "static/poinsettia-logo.png",
    "templates/documentation-guide.html",
    "templates/documentation.html",
    "templates/eula.html",
    "templates/home.html",
    "templates/index.html",
    "templates/privacy.html",
    "tests/__init__.py",
    "tests/test_windows_release_guards.py",
    "windows_release/__init__.py",
    "windows_release/README.md",
    "windows_release/BUILD_WINDOWS.md",
    "windows_release/GITHUB_RELEASE.md",
    "windows_release/requirements.txt",
    "windows_release/run_windows.py",
    "windows_release/open_source_credits.txt",
    "windows_release/installer/Poinsettia.iss",
    # The builder stages this template even for an Inno-only build.
    "windows_release/msix/AppxManifest.xml.in",
    "windows_release/legal/eula.md",
    "windows_release/legal/privacy.md",
    "windows_release/models/Modelfile.p2",
    "windows_release/models/Modelfile.p3",
    "windows_release/models/Modelfile.p4-candor",
    "windows_release/models/Modelfile.p4-fax",
    "windows_release/poinsettia_windows/__init__.py",
    "windows_release/poinsettia_windows/app.py",
    "windows_release/poinsettia_windows/config.py",
    "windows_release/poinsettia_windows/desktop_shell.py",
    "windows_release/poinsettia_windows/hardware.py",
    "windows_release/poinsettia_windows/ollama.py",
    "windows_release/poinsettia_windows/security.py",
    "windows_release/poinsettia_windows/site_mirror.py",
    "windows_release/tools/build_release.ps1",
    "windows_release/tools/compile_site.py",
    "windows_release/tools/minify.py",
    "windows_release/tools/obfuscate.py",
    "windows_release/tools/export_build_source.py",
    "windows_release/web/app.css",
    "windows_release/web/app.js",
    "windows_release/web/desktop_shell.css",
    "windows_release/web/desktop_shell.html",
    "windows_release/web/desktop_shell.js",
    "windows_release/web/favicon.svg",
    "windows_release/web/index.html",
)


def main() -> None:
    contents = {}
    for name in FILES:
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            raise SystemExit(f"Missing or unsafe build input: {name}")
        contents[name] = source.read_bytes()
    manifest = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(contents.items())
    ).encode("ascii")
    contents["SOURCE_SHA256SUMS.txt"] = manifest

    output = ROOT / "releases" / "Poinsettia-Windows-Build-Source.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            archive.writestr(name, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise SystemExit("ZIP integrity verification failed.")
        if set(archive.namelist()) != set(contents):
            raise SystemExit("ZIP contains unexpected entries.")
        for name, data in contents.items():
            if archive.read(name) != data:
                raise SystemExit(f"ZIP content mismatch: {name}")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii")
    print(f"Verified {len(contents)} entries: {output.relative_to(ROOT)}")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()