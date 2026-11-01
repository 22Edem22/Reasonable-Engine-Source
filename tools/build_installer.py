"""Build the complete Windows installer for Reasonable Engine.

Pipeline:
    1. compile the bytecode-only runtime (engine_source_pyc);
    2. build ReasonablePlayer.exe (embedded Python + pygame);
    3. build the portable Python runtime (pygame + Pillow);
    4. build ReasonableEngine.exe (self-test also checks the player);
    5. stage installer files;
    6. compile installer/ReasonableEngine.iss with Inno Setup.

Usage:
    python tools/build_installer.py
    python tools/build_installer.py --skip-python --skip-player
    python tools/build_installer.py --install-innosetup

Inno Setup is required only for the final step. If it is missing, install it
with ``winget install --id JRSoftware.InnoSetup -e`` or pass
``--install-innosetup`` to let this script run that command.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "reasonable" / "version.py"
ISS = ROOT / "installer" / "ReasonableEngine.iss"
PAYLOAD_NAME = "installer_payload"


def _ensure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _read_version() -> tuple[str, str]:
    namespace: dict[str, str] = {}
    try:
        exec(VERSION_FILE.read_text(encoding="utf-8"), namespace)
    except OSError:
        return "0.0.0", "RE-0.01"
    version = str(namespace.get("VERSION") or "0.0.0")
    label = str(namespace.get("VERSION_LABEL") or version)
    return version, label


def _run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> int:
    print("> " + " ".join(str(part) for part in command))
    return subprocess.run(command, cwd=str(cwd), env=env).returncode


def _find_iscc(explicit: str = "") -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_value = os.environ.get("INNO_SETUP_COMPILER") or os.environ.get("ISCC")
    if env_value:
        candidates.append(Path(env_value).expanduser())
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    if found:
        candidates.append(Path(found))
    for base in (
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")),
    ):
        for sub in ("Inno Setup 6", "Inno Setup 5", r"Programs\Inno Setup 6"):
            candidates.append(Path(base) / sub / "ISCC.exe")
    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                try:
                    key = winreg.OpenKey(
                        hive,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
                        0,
                        winreg.KEY_READ | view,
                    )
                except OSError:
                    continue
                try:
                    location, _ = winreg.QueryValueEx(key, "InstallLocation")
                except OSError:
                    continue
                finally:
                    key.Close()
                if location:
                    candidates.append(Path(location) / "ISCC.exe")
    except Exception:
        pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _install_innosetup() -> bool:
    winget = shutil.which("winget")
    if not winget:
        print("winget не найден. Установите Inno Setup вручную: https://jrsoftware.org/isdl.php")
        return False
    print("Устанавливаю Inno Setup через winget…")
    result = _run(
        [
            winget,
            "install",
            "--id",
            "JRSoftware.InnoSetup",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        ]
    )
    return result == 0


def _stage_payload(
    dist: Path,
    payload: Path,
    portable_python: Path,
) -> None:
    if payload.exists():
        shutil.rmtree(payload)
    payload.mkdir(parents=True, exist_ok=True)
    for name in ("ReasonableEngine.exe", "ReasonablePlayer.exe"):
        source = dist / name
        if not source.is_file():
            raise FileNotFoundError(f"Не найден {source}")
        shutil.copy2(source, payload / name)
    for name, target in (
        ("EULA.txt", "EULA.txt"),
        ("THIRD_PARTY_NOTICES.txt", "THIRD_PARTY_NOTICES.txt"),
    ):
        source = ROOT / "installer" / name
        if not source.is_file():
            raise FileNotFoundError(f"Не найден {source}")
        shutil.copy2(source, payload / target)
    readme = ROOT / "README.md"
    if readme.is_file():
        shutil.copy2(readme, payload / "README.md")

    if not portable_python.is_dir():
        raise FileNotFoundError(
            f"Не найдена портативная среда Python: {portable_python}. "
            "Запустите tools/build_portable_python.py."
        )
    target = payload / "runtime" / "python"
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Копирую портативный Python в {target} …")
    shutil.copytree(portable_python, target)


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8()
    parser = argparse.ArgumentParser(description="Собрать установщик Reasonable Engine")
    parser.add_argument("--dist", default=str(ROOT / "dist"), help="Папка с EXE и установщиком")
    parser.add_argument("--payload", default=str(ROOT / "dist" / PAYLOAD_NAME))
    parser.add_argument("--protected", default=str(ROOT / "build" / "protected" / "engine_source_pyc"))
    parser.add_argument("--portable-python", default=str(ROOT / "build" / "portable_python" / "python"))
    parser.add_argument("--python-version", default="", help="Версия Python для портативной сборки")
    parser.add_argument("--iscc", default="", help="Полный путь к ISCC.exe")
    parser.add_argument("--install-innosetup", action="store_true", help="Установить Inno Setup через winget")
    parser.add_argument("--skip-protected", action="store_true")
    parser.add_argument("--skip-player", action="store_true")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-editor", action="store_true")
    parser.add_argument("--skip-self-test", action="store_true")
    parser.add_argument("--no-installer", action="store_true", help="Только подготовить payload")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("ОШИБКА: установщик Windows можно собрать только на Windows.")
        return 2

    dist = Path(args.dist).resolve()
    payload = Path(args.payload).resolve()
    protected = Path(args.protected).resolve()
    portable_python = Path(args.portable_python).resolve()
    dist.mkdir(parents=True, exist_ok=True)
    started = time.time()

    if not args.skip_protected:
        code = _run([sys.executable, str(ROOT / "tools" / "build_protected_source.py"), "--output", str(protected)])
        if code != 0:
            return code

    if not args.skip_player:
        command = [sys.executable, str(ROOT / "tools" / "build_player_exe.py"), "--dist", str(dist)]
        if args.skip_self_test:
            command.append("--skip-self-test")
        code = _run(command)
        if code != 0:
            return code

    if not args.skip_python:
        command = [
            sys.executable,
            str(ROOT / "tools" / "build_portable_python.py"),
            "--output",
            str(Path(args.portable_python).resolve().parent),
        ]
        if args.python_version:
            command += ["--python", args.python_version]
        code = _run(command)
        if code != 0:
            return code

    if not args.skip_editor:
        command = [sys.executable, str(ROOT / "tools" / "build_editor_exe.py"), "--dist", str(dist)]
        if args.skip_self_test:
            command.append("--skip-self-test")
        code = _run(command)
        if code != 0:
            return code

    _stage_payload(dist, payload, portable_python)
    print(f"Payload готов: {payload}")
    if args.no_installer:
        return 0

    iscc = _find_iscc(args.iscc)
    if iscc is None and args.install_innosetup:
        if _install_innosetup():
            iscc = _find_iscc(args.iscc)
    if iscc is None:
        print(
            "ОШИБКА: Inno Setup (ISCC.exe) не найден.\n"
            "Установите его: winget install --id JRSoftware.InnoSetup -e\n"
            "или запустите этот скрипт с --install-innosetup.\n"
            f"Payload уже подготовлен: {payload}"
        )
        return 3

    version, label = _read_version()
    output = dist
    command = [
        str(iscc),
        f"/DPayloadDir={payload}",
        f"/DOutputDir={output}",
        f"/DAppVersion={version}",
        f"/DReleaseLabel={label}",
        str(ISS),
    ]
    code = _run(command)
    if code != 0:
        print("ОШИБКА: Inno Setup завершился с ошибкой.")
        return code or 1

    setup = output / f"ReasonableEngine-Setup-{label}.exe"
    if not setup.is_file():
        print(f"ОШИБКА: ожидался {setup}, но файл не создан.")
        return 1
    size_mb = setup.stat().st_size / (1024 * 1024)
    print(
        f"Установщик готов за {time.time() - started:.1f} с: {setup} ({size_mb:.1f} МБ)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
