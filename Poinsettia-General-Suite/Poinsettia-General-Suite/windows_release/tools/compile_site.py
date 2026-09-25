"""Compile the mirrored website backend without shipping Python source files."""

from __future__ import annotations

import argparse
import py_compile
from pathlib import Path

try:
    import python_minifier
except ImportError as exc:  # pragma: no cover - build-only dependency
    raise SystemExit("Install windows_release/requirements.txt before building.") from exc


def minify_source(source: Path) -> str:
    """Minify application code before compiling it to sourceless bytecode."""
    return python_minifier.minify(
        source.read_text(encoding="utf-8"),
        rename_locals=True,
        remove_annotations=True,
        remove_pass=True,
    )


def compile_module(source: Path, destination: Path) -> None:
    target = destination / f"{source.stem}.pyc"
    temporary_source = destination / f".{source.stem}.obfuscated.py"
    try:
        temporary_source.write_text(minify_source(source), encoding="utf-8")
        py_compile.compile(
            str(temporary_source),
            cfile=str(target),
            dfile=f"{source.stem}.py",
            doraise=True,
        )
    finally:
        temporary_source.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)

    for module_name in ("main.py", "db.py"):
        source = source_root / module_name
        if not source.is_file():
            raise SystemExit(f"Required website module was not found: {source}")
        compile_module(source, destination)

    print(f"Obfuscated sourceless website runtime written to {destination}")


if __name__ == "__main__":
    main()