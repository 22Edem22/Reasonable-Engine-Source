# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for ``ReasonablePlayer.exe``.

The player is a tiny windowed executable that embeds Python and pygame. It runs
a generated project's ``main.py`` directly, so projects start without an
installed Python and without opening a second editor window.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()


def collect_pygame_data() -> list[tuple[str, str]]:
    """Ship pygame's example assets and optional DLLs when they exist."""
    rows: list[tuple[str, str]] = []
    try:
        import pygame
    except Exception:
        return rows
    package = Path(pygame.__file__).resolve().parent
    for relative in ("pygame_icon.bmp", "freesansbold.ttf", "lib", "docs"):
        path = package / relative
        if path.is_file():
            rows.append((str(path), "pygame"))
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    rows.append((str(child), f"pygame/{child.relative_to(package).parent.as_posix()}"))
    return rows


hidden = collect_submodules("pygame")
hidden += [
    "pygame._sdl2",
    "pygame.mixer",
    "pygame.mixer.music",
    "pygame.font",
    "pygame.image",
    "pygame.transform",
    "pygame.gfxdraw",
    "pygame.draw",
]

a = Analysis(
    [str(ROOT / "tools" / "player_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=collect_pygame_data(),
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6", "PyQt5", "PyQt6", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ReasonablePlayer",
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
