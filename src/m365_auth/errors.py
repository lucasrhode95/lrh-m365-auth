"""Errors raised by shared Microsoft authentication."""

from __future__ import annotations


class AuthError(Exception):
    """Base class for authentication errors that product connectors can present."""


class AuthenticationRequired(AuthError):
    """No accepted credential is available for one profile."""

    def __init__(self, message: str, *, command: str) -> None:
        super().__init__(f"{message} Run `{command}` in a terminal, then retry.")
        self.command = command


class AccountMismatch(AuthError):
    """A cached or requested credential belongs to a different active Microsoft account."""


class SecureStorageUnavailable(AuthError):
    """Encrypted token storage cannot be used; plaintext fallback is never implicit."""


class AuthConfigurationError(AuthError):
    """The configured profile or shared auth state is invalid."""


class AuthUpstream(AuthError):
    """Microsoft identity service could not be reached or returned an unexpected response."""
