"""OS-backed protection for quarantine payloads.

Linux deployments must inject a machine-key protector backed by their secret
store. The agent fails closed instead of silently storing quarantine payloads
in plaintext.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from .compat import Protocol


class PayloadProtectionUnavailable(RuntimeError):
    """Raised when encrypted local storage is not configured."""


class PayloadProtector(Protocol):
    def protect(self, plaintext: bytes) -> bytes: ...

    def unprotect(self, ciphertext: bytes) -> bytes: ...


class UnavailablePayloadProtector:
    """Fail-closed default used when no OS secret provider is configured."""

    def protect(self, plaintext: bytes) -> bytes:
        del plaintext
        raise PayloadProtectionUnavailable("quarantine payload protection unavailable")

    def unprotect(self, ciphertext: bytes) -> bytes:
        del ciphertext
        raise PayloadProtectionUnavailable("quarantine payload protection unavailable")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDpapiProtector:
    """Protect quarantine payloads using machine-scoped Windows DPAPI."""

    _CRYPTPROTECT_LOCAL_MACHINE = 0x4
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self, entropy: bytes = b"nexus-agent-quarantine-v1") -> None:
        if os.name != "nt":
            raise PayloadProtectionUnavailable("Windows DPAPI is only available on Windows")
        self._entropy = entropy

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(data)
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        return _DataBlob(len(data), pointer), buffer

    def _transform(self, data: bytes, *, decrypt: bool) -> bytes:
        data_blob, data_buffer = self._blob(data)
        entropy_blob, entropy_buffer = self._blob(self._entropy)
        output = _DataBlob()
        flags = self._CRYPTPROTECT_UI_FORBIDDEN
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if decrypt:
            success = crypt32.CryptUnprotectData(
                ctypes.byref(data_blob), None, ctypes.byref(entropy_blob), None, None,
                flags, ctypes.byref(output),
            )
        else:
            flags |= self._CRYPTPROTECT_LOCAL_MACHINE
            success = crypt32.CryptProtectData(
                ctypes.byref(data_blob), None, ctypes.byref(entropy_blob), None, None,
                flags, ctypes.byref(output),
            )
        del data_buffer, entropy_buffer
        if not success:
            raise PayloadProtectionUnavailable(f"DPAPI operation failed: {ctypes.GetLastError()}")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def protect(self, plaintext: bytes) -> bytes:
        return self._transform(plaintext, decrypt=False)

    def unprotect(self, ciphertext: bytes) -> bytes:
        return self._transform(ciphertext, decrypt=True)
