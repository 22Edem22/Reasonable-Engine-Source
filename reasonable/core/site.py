"""Static-site helpers shared by validation, the agent and scaffolding.

A website project is a plain Python program (``main.py``) that serves the
``site/`` folder with the standard library. This module checks the HTML
without any third-party dependency: local links and assets exist, each page has
a title and a viewport, images have alt text, and no chunk markers remain.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SITE_DIR = "site"
INDEX_NAME = "index.html"

_REMOTE_PREFIXES = (
    "http://",
    "https://",
    "//",
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
    "#",
)
_PLACEHOLDERS = ("@@CHUNK@@", "TODO", "FIXME", "lorem ipsum")


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.title = ""
        self.title_seen = False
        self.has_viewport = False
        self.refs: list[tuple[str, str]] = []
        self.images: list[tuple[str, bool]] = []
        self.ids: list[str] = []
        self.text: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value or "") for name, value in attrs}
        if tag == "html":
            self.lang = values.get("lang", "").strip()
        elif tag == "meta" and values.get("name", "").lower() == "viewport":
            self.has_viewport = True
        elif tag == "title":
            self._in_title = True
            self.title_seen = True
        elif tag == "img":
            self.images.append((values.get("src", ""), "alt" in values))
            if values.get("src"):
                self.refs.append(("img", values["src"]))
        elif tag in {"a", "link", "script", "source", "video", "audio"}:
            attr = "href" if tag in {"a", "link"} else "src"
            value = values.get(attr, "")
            if value:
                self.refs.append((tag, value))
        if values.get("id"):
            self.ids.append(values["id"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        self.text.append(data)


def _local_path(page: Path, site_root: Path, reference: str) -> Path | None:
    value = reference.strip()
    if not value or value.startswith(_REMOTE_PREFIXES):
        return None
    value = value.split("#", 1)[0].split("?", 1)[0]
    if not value:
        return None
    if value.startswith("/"):
        target = site_root / value.lstrip("/")
    else:
        target = page.parent / value
    if value.endswith("/"):
        target = target / INDEX_NAME
    try:
        target = target.resolve()
        target.relative_to(site_root.resolve())
    except (OSError, ValueError):
        return None
    return target


def site_root(project_root: str | Path) -> Path:
    return Path(project_root) / SITE_DIR


def site_pages(project_root: str | Path) -> list[Path]:
    root = site_root(project_root)
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*.html") if path.is_file())


def validate_site(project_root: str | Path) -> list[dict[str, Any]]:
    """Return ``{level, message, path}`` issues for the static site."""
    root = Path(project_root)
    site = site_root(root)
    issues: list[dict[str, Any]] = []
    if not site.is_dir():
        return [
            {
                "level": "error",
                "message": "The site/ folder is missing.",
                "path": SITE_DIR,
            }
        ]
    pages = site_pages(root)
    if not pages:
        return [
            {
                "level": "error",
                "message": "No HTML pages found in site/.",
                "path": SITE_DIR,
            }
        ]
    index = site / INDEX_NAME
    if not index.is_file():
        issues.append(
            {
                "level": "error",
                "message": "site/index.html is missing.",
                "path": f"{SITE_DIR}/{INDEX_NAME}",
            }
        )
    for page in pages:
        relative = page.relative_to(root).as_posix()
        parser = _PageParser()
        try:
            parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            issues.append(
                {"level": "error", "message": f"Could not read the page: {exc}", "path": relative}
            )
            continue
        if not parser.title.strip():
            issues.append(
                {
                    "level": "error",
                    "message": "The page has no non-empty <title>.",
                    "path": relative,
                }
            )
        if not parser.has_viewport:
            issues.append(
                {
                    "level": "error",
                    "message": "Missing <meta name=\"viewport\"> for mobile screens.",
                    "path": relative,
                }
            )
        if not parser.lang:
            issues.append(
                {
                    "level": "warning",
                    "message": "The <html> tag has no lang attribute.",
                    "path": relative,
                }
            )
        seen: set[str] = set()
        for value in parser.ids:
            if value in seen:
                issues.append(
                    {
                        "level": "warning",
                        "message": f"Duplicate id=\"{value}\".",
                        "path": relative,
                    }
                )
            seen.add(value)
        for tag, reference in parser.refs:
            target = _local_path(page, site, reference)
            if target is not None and not target.exists():
                issues.append(
                    {
                        "level": "error",
                        "message": f"Broken {tag} reference: {reference}",
                        "path": relative,
                    }
                )
        for source, has_alt in parser.images:
            if source and not has_alt:
                issues.append(
                    {
                        "level": "warning",
                        "message": f"Image without alt text: {source}",
                        "path": relative,
                    }
                )
        text = " ".join(parser.text).lower()
        for marker in _PLACEHOLDERS:
            if marker.lower() in text:
                issues.append(
                    {
                        "level": "warning",
                        "message": f"Placeholder text found: {marker}",
                        "path": relative,
                    }
                )
    if not any(issue["level"] == "error" for issue in issues):
        issues.append(
            {
                "level": "ok",
                "message": "The site structure and local references look correct.",
                "path": SITE_DIR,
            }
        )
    return issues
