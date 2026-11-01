"""Windows and Android export with live progress.

Windows: a self-contained folder (project + vendored runtime + launcher) and an
optional PyInstaller executable. Every stage reports (stage text, stage
percent, overall percent) through a callback, and there is a separate overall
percent for the whole build — the dialog shows both.

Exports go to the user's Desktop by default. Android export produces a
ready-to-build python-for-android/buildozer project packaged as a ZIP, plus
step-by-step instructions and a GitHub Actions workflow.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

from .core.paths import atomic_write_text, now_iso, read_json, slugify
from .core.project import Project

EXPORT_MARKER = ".reasonable-export"
COPY_IGNORE = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".reasonable",
    ".idea",
    ".vscode",
    ".pytest_cache",
    "data.json",
    "ai_config.json",
}

# (stage_text, stage_percent, overall_percent) — the dialog shows the last two
# as separate bars so the user always sees both the step and the whole build.
ProgressCB = Callable[[str, float, float], None]


def desktop_dir() -> Path:
    """The user's Desktop: the default destination for exports."""
    home = Path.home()
    for candidate in (
        Path(os.environ.get("USERPROFILE", "")) / "Desktop" if os.environ.get("USERPROFILE") else None,
        Path(os.environ.get("ONEDRIVE", "")) / "Desktop" if os.environ.get("ONEDRIVE") else None,
        home / "Desktop",
        home / "Рабочий стол",
    ):
        if candidate is not None and candidate.is_dir():
            return candidate
    return home


def exe_file_name(value: str, project: Project) -> str:
    """Validate the user-provided .exe name; latin slug or the project slug."""
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", str(value or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not re.match(r"^[A-Za-z]", cleaned or ""):
        cleaned = slugify(project.name, "project") or "reasonable-app"
    return re.sub(r"[\s]+", "-", cleaned)[:64] or "reasonable-app"


def _safe_name(value: str) -> str:
    return slugify(value, "project")


def _report(progress: ProgressCB | None, stage: str, stage_pct: float, overall: float) -> None:
    if progress is None:
        return
    try:
        progress(stage, max(0.0, min(100.0, stage_pct)), max(0.0, min(100.0, overall)))
    except Exception:
        pass


def _pick_output(project: Project, output: str | Path | None, default_name: str, *, suffix: str = "") -> Path:
    if output:
        path = Path(output).expanduser().resolve()
        if suffix and path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
    else:
        # Default export destination: the Desktop.
        path = desktop_dir() / default_name
    if path.exists():
        # Only overwrite our own previous exports; never a random user folder.
        marker = path / EXPORT_MARKER if path.is_dir() else None
        if path.is_dir() and marker and marker.exists():
            shutil.rmtree(path)
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
        else:
            index = 2
            base = path
            while path.exists():
                path = base.with_name(f"{base.stem if base.suffix else base.name}-{index}{base.suffix}")
                index += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _copy_ignore(directory: str, names: list[str]) -> set[str]:
    result = set()
    for name in names:
        if name in COPY_IGNORE or name.endswith(".pyc") or name.endswith(".spec"):
            result.add(name)
        if name.startswith(".") and name not in {".github"}:
            result.add(name)
    return result


def _copy_project(
    project: Project,
    destination: Path,
    *,
    progress: ProgressCB | None = None,
    stage: str = "Копирую файлы проекта",
    span: tuple[float, float] = (4, 34),
) -> None:
    """Copy the project with incremental progress (never silently hangs)."""
    source = project.root
    files: list[tuple[Path, Path]] = []
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if _copy_ignore(str(path.parent), [relative.name]) or not path.is_file():
            continue
        # Re-check ignore rules for ancestors (rglob alone does not skip dirs).
        if any(part in COPY_IGNORE for part in relative.parts[:-1]):
            continue
        files.append((path, destination / relative))
    total = len(files) or 1
    start, end = span
    chunk = max(1, total // 40)
    for index, (src, dst) in enumerate(files, start=1):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if index % chunk == 0 or index == total:
            fraction = index / total
            _report(progress, f"{stage} · {index}/{total}", fraction * 100, start + (end - start) * fraction)
    # The copy skips bytecode, and a source project may hold plain .py while a
    # release project holds .pyc. Re-vendor so the export always has a complete
    # runtime in the format this build uses.
    from .core.scaffold import vendor_engine

    vendor_engine(destination)


def _make_ico(project: Project, destination: Path) -> Path | None:
    source = project.icon_path
    if source is None:
        return None
    try:
        from PIL import Image

        image = Image.open(source).convert("RGBA")
        target = destination / "app.ico"
        image.save(
            target,
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        return target
    except Exception:
        return None


def _windows_launcher(project: Project, destination: Path) -> Path:
    launcher = destination / "Play.bat"
    atomic_write_text(
        launcher,
        """@echo off
chcp 65001 >nul
title {title}
cd /d "%~dp0"
set "PYTHONPATH=%~dp0_engine;%~dp0;%PYTHONPATH%"
python main.py
if errorlevel 1 (
  echo.
  echo Не удалось запустить проект. Установите Python 3.10+ с python.org
  echo и повторите запуск. Подробности в README_WINDOWS.txt
  pause
)
""".format(title=project.name),
    )
    return launcher


def _windows_readme(project: Project, destination: Path, icon: Path | None) -> None:
    text = f"""# {project.name} — Windows

Готовый экспорт из **Reasonable Engine**. Внутри уже лежит весь код, ассеты и
встроенная копия движка. Перед запуском игры всегда проигрывается заставка
Reasonable Engine.

## Запуск

1. Установите **Python 3.10+** с <https://www.python.org/downloads/windows/>
   (при установке отметьте «Add Python to PATH»).
2. Дважды щёлкните **Play.bat**.
   Или в терминале:

   ```bat
   cd /d "{destination}"
   set PYTHONPATH=%CD%\\_engine;%CD%
   python main.py
   ```

Если окно закрывается сразу — запустите `Play.bat` и прочитайте сообщение.

## Состав

```
Play.bat            запуск
main.py             код проекта
assets/             спрайты, фоны, иконка
_engine/            встроенный Reasonable Engine
progress/           история разработки
AGENT_GUIDE.md      документация для ИИ-агента
```

## Android

В редакторе: **Файл → Экспорт → Android-пакет**. Сборка APK выполняется на
Linux/WSL, потому что buildozer не поддерживает Windows напрямую.

## Для разработчика

```bat
re.bat status
re.bat validate
re.bat run --headless
```

Экспортировано: {now_iso()}.
"""
    if icon is not None:
        text += "\nИконка приложения: `app.ico`.\n"
    atomic_write_text(destination / "README_WINDOWS.txt", text)


def export_windows(
    project: Project,
    output: str | Path | None = None,
    *,
    mode: str = "folder",
    one_file: bool = False,
    exe_name: str = "",
    progress: ProgressCB | None = None,
) -> dict[str, Any]:
    name = _safe_name(project.name) + "-windows"
    destination = _pick_output(project, output, name)
    if mode == "pyinstaller":
        return _export_windows_pyinstaller(
            project,
            destination,
            one_file=one_file,
            exe_name=exe_name,
            progress=progress,
        )

    _report(progress, "Подготовка", 0, 0)
    destination.mkdir(parents=True, exist_ok=True)
    _report(progress, "Подготовка", 100, 4)
    _copy_project(project, destination, progress=progress, span=(4, 40))
    _report(progress, "Иконка и лаунчер", 10, 62)
    atomic_write_text(destination / EXPORT_MARKER, f"Reasonable Engine export {now_iso()}\n")
    icon = _make_ico(project, destination)
    launcher = _windows_launcher(project, destination)
    _windows_readme(project, destination, icon)
    atomic_write_text(
        destination / "config.json",
        """{
  "exported_by": "Reasonable Engine",
  "platform": "windows",
  "created_at": "%s"
}
"""
        % now_iso(),
    )
    _report(progress, "Финализация", 100, 100)
    return {
        "ok": True,
        "target": "windows",
        "mode": "folder",
        "path": str(destination),
        "launcher": str(launcher),
        "icon": str(icon) if icon else "",
        "message": "Папка Windows готова. Запускайте Play.bat.",
    }


def _find_pyinstaller() -> str | None:
    try:
        import PyInstaller  # noqa: F401

        return sys.executable
    except ImportError:
        return None


def _export_windows_pyinstaller(
    project: Project,
    destination: Path,
    *,
    one_file: bool = False,
    exe_name: str = "",
    progress: ProgressCB | None = None,
) -> dict[str, Any]:
    python = _find_pyinstaller()
    if python is None:
        raise RuntimeError(
            "PyInstaller не установлен. Установите его командой "
            "`python -m pip install pyinstaller` или выберите режим «Папка Windows»."
        )
    work = destination.parent / (destination.name + "-build")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    source = work / "source"
    _report(progress, "Подготовка", 0, 0)
    _copy_project(project, source, progress=progress, span=(4, 34))
    from .core.scaffold import vendor_engine

    # The exported executable embeds the runtime into PyInstaller's archive, so
    # it needs importable source at build time and exposes no .py files anyway.
    _report(progress, "Встраиваю движок", 60, 40)
    vendor_engine(source, protected=False)
    _report(progress, "Встраиваю движок", 100, 48)
    icon = _make_ico(project, work)
    _report(progress, "Иконка и конфигурация", 100, 58)

    binary_name = exe_file_name(exe_name, project)
    command = [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        binary_name,
        "--distpath",
        str(destination),
        "--workpath",
        str(work / "pyinstaller"),
        "--specpath",
        str(work),
        "--paths",
        str(source / "_engine"),
        "--add-data",
        f"{source / 'assets'}{os.pathsep}assets",
        "--add-data",
        f"{source / '_engine' / 'reasonable'}{os.pathsep}reasonable",
        "--collect-data",
        "reasonable",
        # The editor and templates never belong inside a game/app executable:
        # pulling them in made builds huge and could even break the exe.
        "--exclude-module",
        "PySide6",
        "--exclude-module",
        "shiboken6",
        "--exclude-module",
        "reasonable.editor",
        "--exclude-module",
        "reasonable.templates",
    ]
    if icon is not None:
        command += ["--icon", str(icon)]
    if one_file:
        command.append("--onefile")
    command.append(str(source / "main.py"))

    process = subprocess.Popen(
        command,
        cwd=str(source),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    log_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        log_lines.append(line)
        if len(log_lines) % 12 == 0:
            # Forward motion while PyInstaller works; exact percent is unknowable.
            local = min(100.0, len(log_lines) * 0.35)
            _report(progress, "Сборка exe (PyInstaller)", local, 58 + local * 0.36)
    code = process.wait()
    if code != 0:
        log = "".join(log_lines)
        atomic_write_text(work / "pyinstaller.log", log)
        raise RuntimeError(f"PyInstaller завершился с ошибкой. Лог: {work / 'pyinstaller.log'}")
    exe = destination / (binary_name + ".exe")
    if not exe.exists():
        found = sorted(destination.glob("*.exe"))
        if not found:
            atomic_write_text(work / "pyinstaller.log", "".join(log_lines))
            raise RuntimeError("PyInstaller не создал .exe. Лог: " + str(work / "pyinstaller.log"))
        exe = found[0]
    # Frozen templates read the manifest next to the executable.
    try:
        shutil.copy2(source / "project.json", destination / "project.json")
    except OSError:
        pass
    atomic_write_text(destination / EXPORT_MARKER, f"Reasonable Engine PyInstaller export {now_iso()}\n")
    _report(progress, "Финализация", 100, 100)
    return {
        "ok": True,
        "target": "windows",
        "mode": "pyinstaller",
        "path": str(destination),
        "exe": str(exe) if exe.exists() else "",
        "message": f"Windows .exe собран: {exe.name}.",
    }


# ---------------------------------------------------------------------------
# Android
# ---------------------------------------------------------------------------


def _android_spec(project: Project) -> str:
    window = project.manifest.get("window") or {}
    android = project.manifest.get("android") or {}
    orientation = str(android.get("orientation") or project.manifest.get("orientation") or "landscape")
    orientation = "portrait" if orientation == "portrait" else "landscape"
    slug = _safe_name(project.name).replace("-", "_") or "reasonable_app"
    package_name = str(android.get("package") or f"org.reasonable.{slug}").replace("-", "_")
    if "." in package_name:
        domain, _, pkg = package_name.rpartition(".")
    else:
        domain, pkg = "org.reasonable", package_name
    version = str(android.get("version") or "1.0.0")
    return f"""[app]

# Reasonable Engine / pygame-ce Android package
title = {project.name}
package.name = {pkg}
package.domain = {domain}

source.dir = .
source.include_exts = py,png,jpg,jpeg,webp,ogg,wav,mp3,ttf,otf,json,txt,md,csv
source.exclude_dirs = dist,build,.git,__pycache__,.github,.reasonable,tests
source.exclude_patterns = *.pyc,*.spec,data.json,ai_config.json

version = {version}
requirements = python3,pygame
# pygame-ce часто быстрее; если ваша версия p4a поддерживает рецепт:
# requirements = python3,pygame-ce

orientation = {orientation}
fullscreen = 1
android.wakelock = True
android.archs = arm64-v8a, armeabi-v7a
android.api = 34
android.minapi = 24
android.ndk_api = 24
android.accept_sdk_license = True
android.allow_backup = True
android.permissions = VIBRATE
android.release_artifact = apk
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
presplash.color = #080C14

# Подпись release (заполните перед публикацией):
# android.release_artifact = aab
# android.signing = True
# android.keystore = release.keystore
# android.keystore_alias = reasonable
# android.keystore_pwd = ...
# android.key_pwd = ...

[buildozer]
log_level = 2
warn_on_root = 1
"""


def _android_readme(project: Project, destination: Path, zip_path: Path | None = None) -> None:
    zip_line = f"\nГотовый архив: `{zip_path.name}`\n" if zip_path else ""
    text = f"""# {project.name} — Android-пакет

Этот пакет создан **Reasonable Engine** и готов к сборке через
[python-for-android](https://github.com/kivy/python-for-android) / buildozer.
{zip_line}
## Важно

Buildozer работает на **Linux** (или в **WSL2** на Windows), потому что ему нужны
Android SDK/NDK и инструменты сборки. На Windows запустите WSL:

```powershell
wsl --install
```

## Сборка (Ubuntu 22.04+ / WSL)

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool \\
  pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo6 cmake \\
  libffi-dev libssl-dev
pip install --user buildozer cython
export PATH="$HOME/.local/bin:$PATH"

cd {destination.name}
buildozer -v android debug
```

APK появится в `bin/`. Установка на устройство:

```bash
adb install -r bin/*.apk
```

Первая сборка скачивает Android SDK/NDK и занимает 15–40 минут.

## GitHub Actions

В пакете есть `.github/workflows/android.yml`. Загрузите проект в репозиторий
GitHub — APK соберётся автоматически во вкладке **Actions** (артефакт `apk`).

## Что внутри

```
main.py                 запуск
buildozer.spec          конфигурация сборки
assets/                 иконка, presplash, спрайты
_engine/reasonable/     движок (pygame-only)
progress/               история разработки
README_ANDROID.md       эта инструкция
```

## Управление

Игра/приложение использует касания и экранный джойстик, если он добавлен в коде.
Заставка Reasonable Engine проигрывается перед запуском автоматически.
Ориентация экрана: **{project.manifest.get('orientation', 'landscape')}**.

## Release-подпись

1. Создайте keystore:
   ```bash
   keytool -genkey -v -keystore release.keystore -alias reasonable \\
     -keyalg RSA -keysize 2048 -validity 10000
   ```
2. Раскомментируйте блок подписи в `buildozer.spec` и укажите пароли.
3. `buildozer android release`.

## Отладка

- Логи: `adb logcat | grep -i python`
- Быстрый прогон без окна на ПК:
  `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy RE_FRAMES=5 python main.py`
- Если p4a не находит pygame, замените в `buildozer.spec`
  `requirements = python3,pygame` на поддерживаемую вашей версией p4a строку.

Экспортировано: {now_iso()}.
"""
    atomic_write_text(destination / "README_ANDROID.md", text)


def _android_workflow() -> str:
    return """name: Build Android APK

on:
  workflow_dispatch:
  push:
    branches: [ main, master ]

jobs:
  build:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: |
          sudo apt update
          sudo apt install -y git zip unzip openjdk-17-jdk autoconf libtool \\
            pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo6 \\
            cmake libffi-dev libssl-dev
          pip install buildozer cython
      - name: Cache buildozer
        uses: actions/cache@v4
        with:
          path: |
            ~/.buildozer
            .buildozer
          key: buildozer-${{ hashFiles('buildozer.spec') }}
      - name: Build debug APK
        run: buildozer -v android debug
      - uses: actions/upload-artifact@v4
        with:
          name: apk
          path: bin/*.apk
"""


def export_android(
    project: Project,
    output: str | Path | None = None,
    *,
    zip_result: bool = True,
    progress: ProgressCB | None = None,
) -> dict[str, Any]:
    name = _safe_name(project.name) + "-android"
    archive_override: Path | None = None
    if output:
        out_path = Path(output).expanduser()
        if out_path.suffix.lower() == ".zip":
            archive_override = out_path.resolve()
            output = archive_override.with_suffix("")
    destination = _pick_output(project, output, name)
    _report(progress, "Подготовка", 0, 0)
    destination.mkdir(parents=True, exist_ok=True)
    _report(progress, "Подготовка", 100, 5)
    _copy_project(project, destination, progress=progress, stage="Копирую файлы проекта", span=(5, 35))
    from .core.scaffold import vendor_engine

    # python-for-android rebuilds the runtime for the device, so an Android
    # package always gets importable source rather than host-specific .pyc.
    _report(progress, "Встраиваю движок", 60, 42)
    vendor_engine(destination, protected=False)
    _report(progress, "Встраиваю движок", 100, 50)
    # The entry point must be main.py for buildozer.
    if project.entry.name != "main.py":
        shutil.copy2(project.entry, destination / "main.py")
    # buildozer needs a PNG icon and presplash.
    icon = destination / "assets" / "icon.png"
    if not icon.exists():
        project_icon = project.icon_path
        if project_icon:
            shutil.copy2(project_icon, icon)
    presplash = destination / "assets" / "presplash.png"
    if not presplash.exists():
        from .core.paths import BRAND_DIR

        brand = BRAND_DIR / "logo_512.png"
        if brand.exists():
            shutil.copy2(brand, presplash)
    atomic_write_text(destination / "buildozer.spec", _android_spec(project))
    _report(progress, "Конфиги и инструкции", 100, 62)
    workflow_dir = destination / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(workflow_dir / "android.yml", _android_workflow())
    _android_readme(project, destination)
    result: dict[str, Any] = {
        "ok": True,
        "target": "android",
        "path": str(destination),
        "message": "Android-проект готов. Собирайте buildozer на Linux/WSL.",
    }
    if zip_result:
        archive_path = archive_override or Path(str(destination) + ".zip")
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if archive_path.exists():
            archive_path.unlink()
        members = [path for path in destination.rglob("*") if path.is_file()]
        total = len(members) or 1
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for index, path in enumerate(members, start=1):
                archive.write(path, Path(destination.name) / path.relative_to(destination))
                if index % 20 == 0 or index == total:
                    fraction = index / total
                    _report(progress, f"Упаковка ZIP · {index}/{total}", fraction * 100, 62 + fraction * 35)
        result["zip"] = str(archive_path)
        result["message"] = f"Android-пакет готов: {archive_path.name}. Собирайте buildozer на Linux/WSL."
    _report(progress, "Финализация", 100, 100)
    return result
