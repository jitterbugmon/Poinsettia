"""Build the Windows release frontend into windows_release/dist."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

try:
    from rjsmin import jsmin
except ImportError as exc:  # pragma: no cover - build-only dependency
    raise SystemExit("Install windows_release/requirements.txt before building.") from exc


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web"
DEST = ROOT / "dist"


def minify_css(value: str) -> str:
    value = re.sub(r"/\*.*?\*/", "", value, flags=re.S)
    value = re.sub(r"\s+", " ", value)
    return re.sub(r"\s*([{}:;,>])\s*", r"\1", value).strip()


def minify_html(value: str) -> str:
    value = re.sub(r"<!--(?!\[if).*?-->", "", value, flags=re.S)
    return re.sub(r">\s+<", "><", value).strip()


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    for file in SOURCE.iterdir():
        destination = DEST / file.name
        if file.suffix == ".html":
            destination.write_text(minify_html(file.read_text()), encoding="utf-8")
        elif file.suffix == ".css":
            destination.write_text(minify_css(file.read_text()), encoding="utf-8")
        elif file.suffix == ".js":
            destination.write_text(jsmin(file.read_text()), encoding="utf-8")
        else:
            shutil.copy2(file, destination)
    print(f"Minified frontend written to {DEST}")


if __name__ == "__main__":
    main()