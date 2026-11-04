"""Reasonable Engine — a small, AI-first 2D engine for games and apps."""

from __future__ import annotations

import warnings

# pygame still imports pkg_resources on some platforms; setuptools marks that
# module as deprecated. Importing Reasonable Engine filters only that exact
# warning before pygame gets a chance to print it, without hiding real errors.
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API.*",
    category=UserWarning,
)

from .version import VERSION, VERSION_LABEL, VERSION_NAME

__all__ = ["VERSION", "VERSION_LABEL", "VERSION_NAME"]
__version__ = VERSION
