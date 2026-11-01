"""Build the Reasonable Engine editor as a Windows .exe.

Usage:
    python tools/build_editor_exe.py
    python tools/build_editor_exe.py --skip-self-test
    python tools/build_editor_exe.py --no-clean --dist dist-test

The build uses ``ReasonableEngine.spec`` (PyInstaller, one-file). After the
build the executable is launched with ``--self-test`` and a temporary
``REASONABLE_HOME``, so a broken bundle fails before it is published.
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
SPEC = ROOT / "ReasonableEngine.spec"


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _read_report(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run_self_test(exe: Path) -> bool:
    temporary = Path(tempfile.mkdtemp(prefix="reasonable-exe-test-"))
    report_path = temporary / "self-test.json"
    home = temporary / "home"
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["REASONABLE_HOME"] = str(home)
    env["REASONABLE_SELF_TEST_REPORT"] = str(report_path)
    env["PYTHONIOENCODING"] = "utf-8"
    print("Проверяю собранный EXE в offscreen-режиме…")
    timeout = 240
    try:
        result = subprocess.run(
            [str(exe), "--self-test"],
            cwd=str(exe.parent),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"ОШИБКА: self-test не завершился за {timeout} секунд.")
        shutil.rmtree(temporary, ignore_errors=True)
        return False
    except OSError as exc:
        print(f"ОШИБКА: не удалось запустить {exe}: {exc}")
        shutil.rmtree(temporary, ignore_errors=True)
        return False

    report = _read_report(report_path)
    checks = report.get("checks") or []
    failed = [item for item in checks if not item.get("ok")]
    if report.get("error"):
        print(report["error"])
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0 or not report.get("ok"):
        print(f"ОШИБКА: self-test вернул код {result.returncode}.")
        for item in failed:
            print(f"  FAIL {item.get('name')}: {item.get('detail', '')}")
        print(f"Отчёт: {report_path}")
        shutil.rmtree(temporary, ignore_errors=True)
        return False
    print(f"Self-test пройден: {len(checks)} проверок, EXE запускает редактор и создаёт проект.")
    shutil.rmtree(temporary, ignore_errors=True)
    return True


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Собрать Reasonable Engine в Windows .exe")
    parser.add_argument("--dist", default=str(ROOT / "dist"), help="Папка для готового EXE")
    parser.add_argument("--work", default=str(ROOT / "build"), help="Рабочая папка PyInstaller")
    parser.add_argument("--clean", dest="clean", action="store_true", default=True, help="Очистить кеш PyInstaller")
    parser.add_argument("--no-clean", dest="clean", action="store_false", help="Не очищать кеш PyInstaller")
    parser.add_argument("--skip-self-test", action="store_true", help="Не запускать self-test после сборки")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("ОШИБКА: Windows .exe можно собрать только на Windows (PyInstaller не кросс-компилирует).")
        return 2
    if not SPEC.is_file():
        print(f"ОШИБКА: не найден {SPEC.name}.")
        return 2

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("ОШИБКА: PyInstaller не установлен. Выполните: python -m pip install pyinstaller")
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

    print(f"Reasonable Engine EXE builder · Python {sys.version.split()[0]}")
    print(f"Спецификация: {SPEC}")
    print("Сборка может занять несколько минут…")
    started = time.time()
    result = _run(command, cwd=ROOT)
    if result.returncode != 0:
        print("ОШИБКА: PyInstaller завершился с ошибкой.")
        return result.returncode or 1

    exe = dist / "ReasonableEngine.exe"
    if not exe.is_file():
        print(f"ОШИБКА: ожидался {exe}, но файл не создан.")
        return 1
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"Сборка завершена за {time.time() - started:.1f} с: {exe} ({size_mb:.1f} МБ)")
    if not args.skip_self_test and not run_self_test(exe):
        return 1
    print("Готово. Запуск: " + str(exe))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
