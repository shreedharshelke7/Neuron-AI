"""Secure production credential storage for Neuron AI.

Implements Windows Credential Manager storage via standard library ctypes (advapi32.dll)
for sensitive API keys (Gemini, ElevenLabs), with in-memory fallback for testing.
Guarantees:
- API keys are NEVER logged or written to disk in plain text.
- Standard generic credentials persisted per-user securely.
- Clean abstraction allowing test injection without mocking global modules.
"""

from __future__ import annotations

import abc
import ctypes
import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Standard target identifiers in Windows Credential Manager
TARGET_GEMINI: str = "NeuronAI/GeminiApiKey"
TARGET_ELEVENLABS: str = "NeuronAI/ElevenLabsApiKey"


class CredentialStore(abc.ABC):
    """Abstract interface for secure credential storage."""

    @abc.abstractmethod
    def get_credential(self, target_name: str) -> Optional[str]:
        """Retrieve a secret string by target name, or None if not found."""

    @abc.abstractmethod
    def set_credential(self, target_name: str, secret: str) -> bool:
        """Store a secret string by target name. Return True if successful."""

    @abc.abstractmethod
    def delete_credential(self, target_name: str) -> bool:
        """Delete a credential by target name. Return True if successful."""


class MemoryCredentialStore(CredentialStore):
    """In-memory credential store for deterministic automated testing and non-Windows environments."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get_credential(self, target_name: str) -> Optional[str]:
        return self._store.get(target_name)

    def set_credential(self, target_name: str, secret: str) -> bool:
        if not secret:
            return False
        self._store[target_name] = secret
        return True

    def delete_credential(self, target_name: str) -> bool:
        if target_name in self._store:
            del self._store[target_name]
            return True
        return False

    def clear(self) -> None:
        self._store.clear()


class WinCredCredentialStore(CredentialStore):
    """Production Windows Credential Manager implementation using Win32 advapi32.dll.

    Zero external dependencies; completely self-contained and PyInstaller compatible.
    """

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self) -> None:
        self._available = sys.platform == "win32"
        if not self._available:
            logger.warning("WinCredCredentialStore instantiated on non-Windows platform.")

    def get_credential(self, target_name: str) -> Optional[str]:
        if not self._available:
            return None

        try:
            from ctypes import wintypes

            advapi32 = ctypes.windll.advapi32

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

            class CREDENTIAL(ctypes.Structure):
                _fields_ = [
                    ("Flags", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR),
                    ("LastWritten", FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.c_void_p),
                    ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR),
                ]

            PCREDENTIAL = ctypes.POINTER(CREDENTIAL)
            p_cred = PCREDENTIAL()

            ok = advapi32.CredReadW(
                target_name,
                self.CRED_TYPE_GENERIC,
                0,
                ctypes.byref(p_cred),
            )
            if not ok or not p_cred:
                return None

            try:
                blob_size = p_cred.contents.CredentialBlobSize
                blob_ptr = p_cred.contents.CredentialBlob
                if blob_size == 0 or not blob_ptr:
                    return None
                raw_bytes = ctypes.string_at(blob_ptr, blob_size)
                return raw_bytes.decode("utf-16le")
            finally:
                advapi32.CredFree(p_cred)

        except Exception as exc:
            logger.debug("Failed to read credential '%s' from Credential Manager: %s", target_name, exc)
            return None

    def set_credential(self, target_name: str, secret: str) -> bool:
        if not self._available or not secret:
            return False

        try:
            from ctypes import wintypes

            advapi32 = ctypes.windll.advapi32

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

            class CREDENTIAL(ctypes.Structure):
                _fields_ = [
                    ("Flags", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR),
                    ("LastWritten", FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                    ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR),
                ]

            secret_bytes = secret.encode("utf-16le")
            blob = (ctypes.c_byte * len(secret_bytes))(*secret_bytes)

            cred = CREDENTIAL(
                Flags=0,
                Type=self.CRED_TYPE_GENERIC,
                TargetName=target_name,
                Comment="Neuron AI secure credential",
                CredentialBlobSize=len(secret_bytes),
                CredentialBlob=blob,
                Persist=self.CRED_PERSIST_LOCAL_MACHINE,
                UserName="NeuronAI",
            )

            ok = advapi32.CredWriteW(ctypes.byref(cred), 0)
            return bool(ok)

        except Exception as exc:
            logger.error("Failed to write credential '%s' to Credential Manager: %s", target_name, exc)
            return False

    def delete_credential(self, target_name: str) -> bool:
        if not self._available:
            return False

        try:
            advapi32 = ctypes.windll.advapi32
            ok = advapi32.CredDeleteW(target_name, self.CRED_TYPE_GENERIC, 0)
            return bool(ok)
        except Exception as exc:
            logger.debug("Failed to delete credential '%s' from Credential Manager: %s", target_name, exc)
            return False


_active_store: Optional[CredentialStore] = None


def get_credential_store() -> CredentialStore:
    """Return the global active CredentialStore instance."""
    global _active_store
    if _active_store is None:
        if sys.platform == "win32":
            _active_store = WinCredCredentialStore()
        else:
            _active_store = MemoryCredentialStore()
    return _active_store


def set_credential_store(store: Optional[CredentialStore]) -> None:
    """Explicitly set the active CredentialStore (for testing and DI)."""
    global _active_store
    _active_store = store


def reset_credential_store() -> None:
    """Reset the active store to default."""
    global _active_store
    _active_store = None


def get_gemini_api_key(store: Optional[CredentialStore] = None) -> Optional[str]:
    """Retrieve the Gemini API key from the credential store."""
    s = store or get_credential_store()
    return s.get_credential(TARGET_GEMINI)


def get_elevenlabs_api_key(store: Optional[CredentialStore] = None) -> Optional[str]:
    """Retrieve the ElevenLabs API key from the credential store."""
    s = store or get_credential_store()
    return s.get_credential(TARGET_ELEVENLABS)


def save_api_credentials(
    gemini_key: str,
    elevenlabs_key: str,
    store: Optional[CredentialStore] = None,
) -> bool:
    """Store both Gemini and ElevenLabs API keys in Windows Credential Manager."""
    s = store or get_credential_store()
    ok_gemini = s.set_credential(TARGET_GEMINI, gemini_key.strip())
    ok_eleven = s.set_credential(TARGET_ELEVENLABS, elevenlabs_key.strip())
    return ok_gemini and ok_eleven


def delete_api_credentials(store: Optional[CredentialStore] = None) -> bool:
    """Remove both Gemini and ElevenLabs credentials from Windows Credential Manager."""
    s = store or get_credential_store()
    ok_gemini = s.delete_credential(TARGET_GEMINI)
    ok_eleven = s.delete_credential(TARGET_ELEVENLABS)
    return ok_gemini or ok_eleven
