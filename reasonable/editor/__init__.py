"""Reasonable Engine editor package (PySide6)."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    from .main_window import main as _main

    return _main(argv)


__all__ = ["main"]
