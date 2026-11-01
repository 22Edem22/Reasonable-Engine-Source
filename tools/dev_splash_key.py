"""Developer-only helper for the Reasonable Engine splash key.

The "Reasonable Engine" intro splash always plays before every project and
cannot be disabled by users: no project.json flag, no environment variable.
The single bypass is a personal key known only to the engine developer: the
runtime compares the SHA-256 of the RE_SPLASH_DEV_TOKEN environment variable
against DEV_TOKEN_HASH baked into the bytecode-only runtime.

Usage (run from the engine checkout, developer only):

    python tools/dev_splash_key.py --gen        create a new random key + hash
    python tools/dev_splash_key.py --hash KEY   print the hash of a key
    python tools/dev_splash_key.py --check KEY  verify a key against the build

After generating a key once, set it for your user account:

    setx RE_SPLASH_DEV_TOKEN <key>

Then every project on this machine skips the intro (developer machines only).
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reasonable Engine developer splash key")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--gen", action="store_true", help="generate a new random key + hash")
    group.add_argument("--hash", metavar="KEY", help="print the SHA-256 hash of KEY")
    group.add_argument("--check", metavar="KEY", help="verify KEY against the built-in hash")
    args = parser.parse_args(argv)

    if args.gen:
        key = secrets.token_hex(16)
        print(f"Ключ разработчика: {key}")
        print(f"Его SHA-256 (вшивается в движок): {_hash(key)}")
        print("Установка на своём компьютере:  setx RE_SPLASH_DEV_TOKEN " + key)
        return 0
    if args.hash:
        print(_hash(args.hash))
        return 0
    try:
        from reasonable.runtime.splash import DEV_TOKEN_HASH, developer_splash_bypass
    except ImportError:
        print("Не удалось импортировать reasonable.runtime.splash", file=sys.stderr)
        return 2
    match = _hash(args.check) == DEV_TOKEN_HASH
    print("ДА — заставка будет пропущена на этой машине." if match else "НЕТ — хеш не совпадает.")
    return 0 if match else 1


if __name__ == "__main__":
    raise SystemExit(main())
