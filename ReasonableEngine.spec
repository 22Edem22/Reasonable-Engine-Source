# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Reasonable Engine Windows editor.

The frozen application needs four copies of engine-owned files:

* ``reasonable/assets`` and ``reasonable/templates`` in their normal package
  locations, because the editor reads them directly;
* ``docs`` and ``README.md`` at the bundle root, because ``ENGINE_ROOT`` points
  there in a frozen build;
* ``engine_source/reasonable`` as plain source, used for Android exports and as
  a fallback when the protected tree is missing;
* ``engine_source_pyc/reasonable`` as bytecode only. Generated Windows projects
  vendor this copy, so the engine source is not exposed to end users.

Build the protected tree first with ``python tools/build_protected_source.py``;
``tools/build_installer.py`` does that automatically.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()
PACKAGE = ROOT / "reasonable"
PROTECTED = ROOT / "build" / "protected" / "engine_source_pyc" / "reasonable"


def collect_tree(source: Path, prefix: str, *, excluded_dirs=(), excluded_suffixes=()) -> list[tuple[str, str]]:
    """Return hook-style (source_file, target_dir) pairs without caches."""
    source = Path(source)
    excluded_dirs = set(excluded_dirs)
    excluded_suffixes = set(excluded_suffixes)
    rows: list[tuple[str, str]] = []
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if path.is_dir():
            continue
        if any(part in excluded_dirs for part in relative.parts):
            continue
        if path.suffix.lower() in excluded_suffixes:
            continue
        target_dir = Path(prefix) / relative.parent
        rows.append((str(path), str(target_dir)))
    return rows


datas = []
# Plain source used by vendor_engine() in generated projects. Editor and
# templates are not vendored into projects, so keep them out of this copy.
datas += collect_tree(
    PACKAGE,
    "engine_source/reasonable",
    excluded_dirs={"editor", "templates", "__pycache__", ".pytest_cache"},
    excluded_suffixes={".pyc", ".pyo"},
)
# Runtime assets and templates at their import-time locations.
datas += collect_tree(
    PACKAGE / "assets",
    "reasonable/assets",
    excluded_dirs={"__pycache__"},
    excluded_suffixes={".pyc", ".pyo"},
)
datas += collect_tree(
    PACKAGE / "templates",
    "reasonable/templates",
    excluded_dirs={"__pycache__"},
    excluded_suffixes={".pyc", ".pyo"},
)
datas += collect_tree(
    ROOT / "docs",
    "docs",
    excluded_dirs={"__pycache__"},
    excluded_suffixes={".pyc", ".pyo"},
)
datas.append((str(ROOT / "README.md"), "."))

if PROTECTED.is_dir():
    protected_rows = collect_tree(
        PROTECTED,
        "engine_source_pyc/reasonable",
        excluded_dirs={"__pycache__"},
        excluded_suffixes={".py", ".pyo"},
    )
    datas += protected_rows
    print(f"[ReasonableEngine] protected runtime: {len(protected_rows)} files")
else:
    print(
        "[ReasonableEngine] WARNING: build/protected/engine_source_pyc is missing; "
        "projects will vendor plain source. Run tools/build_protected_source.py."
    )

a = Analysis(
    [str(ROOT / "run_editor.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("reasonable"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ReasonableEngine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "reasonable" / "assets" / "brand" / "logo.ico"),
)
