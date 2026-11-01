"""Build ``ReasonablePlayer.exe``.

Usage:
    python tools/build_player_exe.py
    python tools/build_player_exe.py --skip-self-test

The player embeds Python + pygame and runs a generated project directly. It is
shipped next to the editor so installed builds never need a system Python.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "ReasonablePlayer.spec"


def _ensure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def run_self_test(exe: Path) -> bool:
    temporary = Path(tempfile.mkdtemp(prefix="reasonable-player-test-"))
    report_path = temporary / "self-test.json"
    env = dict(os.environ)
    env["REASONABLE_PLAYER_SELF_TEST_REPORT"] = str(report_path)
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    env["PYTHONIOENCODING"] = "utf-8"
    print("Проверяю ReasonablePlayer.exe…")
    try:
        result = subprocess.run(
            [str(exe), "--self-test"],
            cwd=str(exe.parent),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"ОШИБКА: не удалось проверить player: {exc}")
        shutil.rmtree(temporary, ignore_errors=True)
        return False

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = {}
    checks = report.get("checks") or []
    failed = [item for item in checks if not item.get("ok")]
    if report.get("error"):
        print(report["error"])
    if result.returncode != 0 or not report.get("ok"):
        print(f"ОШИБКА: self-test player вернул код {result.returncode}.")
        for item in failed:
            print(f"  FAIL {item.get('name')}: {item.get('detail', '')}")
        shutil.rmtree(temporary, ignore_errors=True)
        return False
    print(f"Self-test player пройден: pygame {next((c['detail'] for c in checks if c['name'] == 'pygame import'), '')}.")
    shutil.rmtree(temporary, ignore_errors=True)
    return True


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8()
    parser = argparse.ArgumentParser(description="Собрать ReasonablePlayer.exe")
    parser.add_argument("--dist", default=str(ROOT / "dist"), help="Папка для готового EXE")
    parser.add_argument("--work", default=str(ROOT / "build" / "player"), help="Рабочая папка PyInstaller")
    parser.add_argument("--no-clean", dest="clean", action="store_false", default=True)
    parser.add_argument("--skip-self-test", action="store_true")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("ОШИБКА: ReasonablePlayer.exe можно собрать только на Windows.")
        return 2
    if not SPEC.is_file():
        print(f"ОШИБКА: не найден {SPEC.name}.")
        return 2
    try:
        import pygame  # noqa: F401
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        print(f"ОШИБКА: {exc}. Выполните: python -m pip install -r requirements.txt pyinstaller")
        return 2

    dist = Path(args.dist).resolve()
    work = Path(args.work).resolve()
    dist.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
    ]
    if args.clean:
        command.append("--clean")
    command.append(str(SPEC))

    print(f"Reasonable Player builder · Python {sys.version.split()[0]}")
    started = time.time()
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode != 0:
        print("ОШИБКА: PyInstaller завершился с ошибкой.")
        return result.returncode or 1

    exe = dist / "ReasonablePlayer.exe"
    if not exe.is_file():
        print(f"ОШИБКА: ожидался {exe}, но файл не создан.")
        return 1
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"Сборка player завершена за {time.time() - started:.1f} с: {exe} ({size_mb:.1f} МБ)")
    if not args.skip_self_test and not run_self_test(exe):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
