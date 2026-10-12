"""Shared authentication for the local Microsoft 365 connector family."""

from m365_auth.errors import (
    AccountMismatch,
    AuthConfigurationError,
    AuthenticationRequired,
    AuthError,
    AuthUpstream,
    SecureStorageUnavailable,
)
from m365_auth.models import AccessToken, Account, BootstrapResult, CacheStatus, ProfileStatus
from m365_auth.profiles import PROFILES, TokenProfile
from m365_auth.tokens import TokenProvider

__all__ = [
    "PROFILES",
    "AccessToken",
    "Account",
    "AccountMismatch",
    "AuthConfigurationError",
    "AuthError",
    "AuthUpstream",
    "AuthenticationRequired",
    "BootstrapResult",
    "CacheStatus",
    "ProfileStatus",
    "SecureStorageUnavailable",
    "TokenProfile",
    "TokenProvider",
]
