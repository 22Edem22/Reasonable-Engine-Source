"""Build the portable Python runtime that ships with the Windows installer.

Usage:
    python tools/build_portable_python.py
    python tools/build_portable_python.py --python 3.13.7
    python tools/build_portable_python.py --offline path/to/python-embed.zip

The result is a self-contained folder containing ``python.exe`` plus the
packages a generated project or the external-agent CLI needs (pygame, Pillow).
It requires no system Python and is copied to ``<install>\\runtime\\python``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "build" / "portable_python"
PYPI_PACKAGES = ("pygame", "Pillow")


def _download(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size > 0:
        print(f"Использую кеш: {destination.name}")
        return destination
    print(f"Скачиваю {url} …")
    request = urllib.request.Request(url, headers={"User-Agent": "ReasonableEngine-Builder"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def _default_version() -> str:
    info = sys.version_info
    return f"{info.major}.{info.minor}.{info.micro}"


def _prepare_layout(python_dir: Path, version: str) -> Path:
    """Remove the embeddable distribution's ``._pth`` isolation file.

    The ``._pth`` file forces isolated mode, which makes Python ignore
    ``PYTHONPATH``. Project launchers rely on it to import the vendored engine
    from ``_engine``. Without the file, Python still finds ``pythonXY.zip`` and
    ``Lib\\site-packages`` next to the executable, but honours ``PYTHONPATH``.
    """
    removed = None
    for candidate in list(python_dir.glob("python*._pth")):
        removed = candidate
        candidate.unlink()
    site_packages = python_dir / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    marker = python_dir / "portable-python.txt"
    marker.write_text(
        f"Reasonable Engine portable Python {version}\n"
        "Embeddable distribution with PYTHONPATH enabled.\n",
        encoding="utf-8",
    )
    return removed or marker


def build(output: Path, *, version: str | None = None, offline: Path | None = None) -> Path:
    version = version or _default_version()
    root = output
    python_dir = root / "python"
    if python_dir.exists():
        shutil.rmtree(python_dir)
    root.mkdir(parents=True, exist_ok=True)

    if offline is not None:
        archive = Path(offline).expanduser().resolve()
        if not archive.is_file():
            raise FileNotFoundError(f"Не найден архив Python: {archive}")
    else:
        name = f"python-{version}-embed-amd64.zip"
        url = f"https://www.python.org/ftp/python/{version}/{name}"
        archive = _download(url, root / "download" / name)

    print(f"Распаковываю {archive.name} …")
    python_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(python_dir)
    exe = python_dir / "python.exe"
    if not exe.is_file():
        raise RuntimeError("В архиве нет python.exe — нужен embed-amd64 пакет.")

    pth = _prepare_layout(python_dir, version)
    print(f"Удалён {pth.name}: PYTHONPATH снова работает (site-packages сохранён)")

    # Bootstrap pip inside the embeddable distribution. It has no ensurepip.
    pip_marker = python_dir / "Lib" / "site-packages" / "pip"
    if not pip_marker.exists():
        get_pip = _download(
            "https://bootstrap.pypa.io/get-pip.py",
            root / "download" / "get-pip.py",
        )
        print("Устанавливаю pip в портативный Python …")
        subprocess.run(
            [str(exe), str(get_pip), "--no-warn-script-location"],
            cwd=str(python_dir),
            check=True,
        )

    print("Устанавливаю pygame и Pillow …")
    subprocess.run(
        [str(exe), "-m", "pip", "install", "--no-warn-script-location", "--upgrade", *PYPI_PACKAGES],
        cwd=str(python_dir),
        check=True,
    )

    print("Проверяю портативный Python …")
    result = subprocess.run(
        [
            str(exe),
            "-c",
            "import json, pygame, PIL; print(json.dumps({'python': __import__('sys').version,"
            " 'pygame': pygame.version.ver, 'pillow': PIL.__version__}))",
        ],
        cwd=str(python_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Портативный Python не прошёл проверку:\n{result.stdout}\n{result.stderr}")
    print("OK " + (result.stdout or "").strip())

    manifest = {
        "python": version,
        "packages": list(PYPI_PACKAGES),
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "check": json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {},
    }
    (root / "portable-python.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Готово: {python_dir}")
    return python_dir


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Собрать портативный Python для установщика")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Папка результата")
    parser.add_argument("--python", default="", help="Версия, например 3.13.7")
    parser.add_argument("--offline", default="", help="Локальный python-*-embed-amd64.zip")
    args = parser.parse_args(argv)
    try:
        build(
            Path(args.output).resolve(),
            version=args.python or None,
            offline=Path(args.offline) if args.offline else None,
        )
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
