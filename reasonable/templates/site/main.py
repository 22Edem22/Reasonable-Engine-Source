"""Serve the static website in site/ with the Python standard library.

Run:
    python main.py
    python main.py --port 8080 --no-browser
    python main.py --check

Works on Windows and Linux without installing anything. No build step.
"""

from __future__ import annotations

import argparse
import http.server
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"


class SiteHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass


def _server(host: str, port: int) -> http.server.ThreadingHTTPServer:
    return http.server.ThreadingHTTPServer((host, port), SiteHandler)


def check() -> int:
    """Smoke-test every page through a real local HTTP server."""
    if not (SITE / "index.html").is_file():
        print("ERROR: site/index.html is missing.", file=sys.stderr)
        return 1
    errors: list[str] = []
    httpd = _server("127.0.0.1", 0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        for page in sorted(SITE.rglob("*.html")):
            url = f"http://127.0.0.1:{port}/{page.relative_to(SITE).as_posix()}"
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    if response.status != 200:
                        errors.append(f"{page.name}: HTTP {response.status}")
            except Exception as exc:  # network errors are test failures here
                errors.append(f"{page.name}: {type(exc).__name__}: {exc}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(list(SITE.rglob('*.html')))} page(s) served successfully.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the project website")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="smoke-test pages and exit")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    httpd = _server(args.host, args.port)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving {SITE} at {url}")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
