"""Shared account, access-token, profile and cache-status data types."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def decode_claims(token: str) -> dict[str, Any]:
    """Decode a JWT payload for display/identity inspection; this does not verify signatures."""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class Account:
    tenant_id: str
    object_id: str
    username: str | None

    @property
    def identity_hash(self) -> str:
        """Full stable hash used by the private shared state marker."""
        return hashlib.sha256(f"{self.tenant_id}:{self.object_id}".encode()).hexdigest()

    @property
    def fingerprint(self) -> str:
        """Short, privacy-preserving key used to bind a connector's local data."""
        return self.identity_hash[:16]

    @classmethod
    def from_msal(cls, account: dict[str, Any]) -> Account:
        object_id, separator, tenant_id = str(account.get("home_account_id", "")).partition(".")
        if not separator or not object_id or not tenant_id:
            raise ValueError("The cached Microsoft account has no stable tenant and object identity.")
        return cls(tenant_id, object_id, account.get("username"))


@dataclass(frozen=True)
class AccessToken:
    profile: str
    value: str = field(repr=False)
    source: str
    expires_on: int | None

    def claims(self) -> dict[str, Any]:
        return decode_claims(self.value)


@dataclass(frozen=True)
class ProfileStatus:
    profile: str
    client_id: str
    scopes: tuple[str, ...]
    purpose: str
    signed_in: bool
    access_token_expires_on: int | None


@dataclass(frozen=True)
class CacheStatus:
    mode: str
    path: Path
    exists: bool
    accounts: tuple[Account, ...]
    profiles: tuple[ProfileStatus, ...]


@dataclass(frozen=True)
class BootstrapResult:
    profile: str
    token: AccessToken | None
    error: Exception | None

    @property
    def ready(self) -> bool:
        return self.token is not None and self.error is None
