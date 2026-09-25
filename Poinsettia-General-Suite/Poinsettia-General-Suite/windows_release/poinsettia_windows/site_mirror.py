from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .config import local_data_root


def _release_bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def _source_root() -> Path:
    bundled = _release_bundle_root() / "site_runtime"
    if bundled.exists():
        return bundled
    # Source checkout: windows_release/poinsettia_windows/site_mirror.py
    return Path(__file__).resolve().parents[2]


def _runtime_modules(source: Path) -> tuple[Path, Path]:
    compiled = (source / "main.pyc", source / "db.pyc")
    if all(path.is_file() for path in compiled):
        return compiled

    development = (source / "main.py", source / "db.py")
    if all(path.is_file() for path in development):
        return development

    raise RuntimeError("The packaged website runtime is incomplete.")


def prepare_site_copy() -> Path:
    """Copy the website runtime into isolated per-user Windows data."""
    source = _source_root()
    destination = local_data_root() / "website"
    destination.mkdir(parents=True, exist_ok=True)

    main_module, database_module = _runtime_modules(source)
    for legacy_source in (destination / "main.py", destination / "db.py"):
        legacy_source.unlink(missing_ok=True)
    shutil.copy2(main_module, destination / main_module.name)
    shutil.copy2(database_module, destination / database_module.name)
    for directory in ("templates", "static"):
        shutil.copytree(source / directory, destination / directory, dirs_exist_ok=True)

    # The copied main.py resolves its database and generated-file paths from
    # its working directory. Keeping that directory per-user isolates the
    # Windows release from the website's database and files.
    (destination / "user_files").mkdir(exist_ok=True)
    return destination


def load_site_app(site_directory: Path):
    """Import the copied website app without modifying the source website."""
    os.chdir(site_directory)
    sys.path.insert(0, str(site_directory))
    import importlib.util
    from importlib.machinery import SourcelessFileLoader

    main_module = site_directory / "main.pyc"
    if main_module.is_file():
        loader = SourcelessFileLoader("poinsettia_windows_copied_site", str(main_module))
        spec = importlib.util.spec_from_file_location(
            "poinsettia_windows_copied_site", main_module, loader=loader
        )
    else:
        main_module = site_directory / "main.py"
        spec = importlib.util.spec_from_file_location(
            "poinsettia_windows_copied_site", main_module
        )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the copied Poinsettia website runtime.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app