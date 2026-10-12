"""Bind API token acquisition to the account that owns a connector service context."""

from __future__ import annotations

from typing import Protocol

from m365_auth.errors import AccountMismatch
from m365_auth.models import AccessToken, Account


class TokenSource(Protocol):
    def get_token(
        self,
        profile: str,
        *,
        force_refresh: bool = False,
        claims_challenge: str | None = None,
    ) -> AccessToken: ...

    def sign_in_command(self, profile: str | None = None) -> str: ...


class AccountBoundTokenSource:
    """A narrow token source that refuses credentials from another account.

    Connector composition roots create one source per account-bound service set and pass it to
    remote adapters. TokenProvider still owns sign-in, cache state and profile validation.
    """

    def __init__(self, source: TokenSource, account: Account) -> None:
        self._source = source
        self._account = account

    def get_token(
        self,
        profile: str,
        *,
        force_refresh: bool = False,
        claims_challenge: str | None = None,
    ) -> AccessToken:
        token = self._source.get_token(
            profile, force_refresh=force_refresh, claims_challenge=claims_challenge
        )
        claims = token.claims()
        tenant_id, object_id = claims.get("tid"), claims.get("oid")
        if not isinstance(tenant_id, str) or not tenant_id or not isinstance(object_id, str) or not object_id:
            raise AccountMismatch(
                "The Microsoft token has no stable account identity; restart the operation."
            )
        if (tenant_id.casefold(), object_id.casefold()) != (
            self._account.tenant_id.casefold(),
            self._account.object_id.casefold(),
        ):
            raise AccountMismatch("The active Microsoft account changed; restart the operation.")
        return token

    def sign_in_command(self, profile: str | None = None) -> str:
        return self._source.sign_in_command(profile)
