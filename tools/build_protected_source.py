"""Compile the vendorable runtime to bytecode only.

Generated projects embed a copy of the engine in ``_engine/``. Shipping plain
``.py`` files there exposes the engine source to every user, so release builds
vendor a sourceless ``.pyc`` tree instead.

Usage:
    python tools/build_protected_source.py
    python tools/build_protected_source.py --output build/protected/engine_source_pyc

The result is a legacy (sourceless) layout: ``reasonable/core/project.pyc`` and
so on, without the corresponding ``.py`` files. This is importable by the
portable Python and by ``ReasonablePlayer.exe`` when both are built with the
same Python version.
"""

from __future__ import annotations

import argparse
import py_compile
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "reasonable"
DEFAULT_OUTPUT = ROOT / "build" / "protected" / "engine_source_pyc"

# The editor is PySide6-only and is never vendored into a project. Templates
# are skipped by ``vendor_engine`` for the same reason (projects keep their own
# rendered copy).
SKIP_DIRS = {"editor", "templates", "__pycache__", ".pytest_cache"}


def _include(relative: Path) -> bool:
    return not any(part in SKIP_DIRS for part in relative.parts)


def build(output: Path) -> Path:
    target = output / "reasonable"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    compiled = 0
    copied = 0
    for source in sorted(PACKAGE.rglob("*")):
        if source.is_dir():
            continue
        relative = source.relative_to(PACKAGE)
        if not _include(relative):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".py":
            py_compile.compile(
                str(source),
                cfile=str(destination.with_suffix(".pyc")),
                dfile=str(relative),
                doraise=True,
            )
            compiled += 1
        elif source.suffix in {".pyc", ".pyo"}:
            continue
        else:
            shutil.copy2(source, destination)
            copied += 1

    # A stray .py in the protected tree would defeat the purpose and could
    # shadow the compiled module. Fail loudly instead of shipping it.
    leftovers = [path for path in target.rglob("*.py") if _include(path.relative_to(target))]
    if leftovers:
        raise RuntimeError(f"В защищённом дереве остались .py: {leftovers[:5]}")

    print(f"Защищённый runtime: {target}")
    print(f"  скомпилировано модулей: {compiled}")
    print(f"  скопировано ресурсов: {copied}")
    print(f"  всего файлов: {sum(1 for _ in target.rglob('*') if _.is_file())}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Собрать bytecode-only копию движка")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Куда положить engine_source_pyc")
    args = parser.parse_args(argv)
    try:
        build(Path(args.output).resolve())
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
