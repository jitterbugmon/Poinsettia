"""Optional Python obfuscation step for the Windows release build.

Obfuscation raises the effort required to inspect bundled Python; it is not a
security boundary. Never place secrets in source code or model prompts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

try:
    import python_minifier
except ImportError as exc:  # pragma: no cover - build-only dependency
    raise SystemExit("Install windows_release/requirements.txt before building.") from exc


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poinsettia_windows"
DEST = ROOT / "build" / "obfuscated" / "poinsettia_windows"


def minify_python(source: Path) -> str:
    return python_minifier.minify(
        source.read_text(encoding="utf-8"),
        rename_locals=True,
        remove_annotations=True,
        remove_pass=True,
    )


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    for source in SOURCE.glob("*.py"):
        (DEST / source.name).write_text(minify_python(source), encoding="utf-8")

    entrypoint = ROOT / "run_windows.py"
    (DEST.parent / entrypoint.name).write_text(minify_python(entrypoint), encoding="utf-8")
    print(f"Obfuscated Python written to {DEST}")


if __name__ == "__main__":
    main()