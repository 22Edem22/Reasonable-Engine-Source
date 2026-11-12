"""Protect API keys at rest with the Windows Data Protection API.

``settings.json`` lives in ``%APPDATA%`` and used to contain provider keys in
plain text. DPAPI ties the ciphertext to the current Windows user, so copying
the file to another account or machine does not reveal the key. The engine has
no cryptography dependency; ``ctypes`` talks to ``crypt32`` directly.

On non-Windows systems (tests, exported runtimes that never touch settings)
the helpers are a no-op and keep plain text.
"""

from __future__ import annotations

import base64
import sys

PREFIX = "dpapi:"


def _dpapi(data: bytes, decrypt: bool) -> bytes | None:
    if sys.platform != "win32" or not data:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        function.restype = wintypes.BOOL
        function.argtypes = [
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
        buffer = ctypes.create_string_buffer(data, len(data))
        blob_in = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        blob_out = DataBlob()
        if not function(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def protect(value: str) -> str:
    """Encrypt a secret for the current Windows user; return it unchanged otherwise."""
    text = str(value or "")
    if not text or text.startswith(PREFIX):
        return text
    encrypted = _dpapi(text.encode("utf-8"), decrypt=False)
    if encrypted is None:
        return text
    return PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect(value: str) -> str:
    """Decrypt a stored secret. A broken value becomes an empty key."""
    text = str(value or "")
    if not text.startswith(PREFIX):
        return text
    try:
        encrypted = base64.b64decode(text[len(PREFIX) :].encode("ascii"), validate=True)
    except Exception:
        return ""
    decrypted = _dpapi(encrypted, decrypt=True)
    if decrypted is None:
        return ""
    try:
        return decrypted.decode("utf-8")
    except UnicodeDecodeError:
        return ""
