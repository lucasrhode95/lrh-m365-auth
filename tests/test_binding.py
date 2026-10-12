from __future__ import annotations

import pytest

from m365_auth import AccessToken, Account, AccountBoundTokenSource, AccountMismatch
from tests.msal_fakes import OTHER_OID, TENANT, USER_OID, jwt


class Tokens:
    def __init__(self, claims: dict[str, str]) -> None:
        self.claims = claims
        self.profiles: list[str] = []

    def get_token(
        self, profile: str, *, force_refresh: bool = False, claims_challenge: str | None = None
    ) -> AccessToken:
        self.profiles.append(profile)
        return AccessToken(profile, jwt(self.claims), "synthetic", None)

    def sign_in_command(self, profile: str | None = None) -> str:
        return f"connector auth {profile or ''}".strip()


def test_account_bound_source_returns_a_token_for_the_service_account() -> None:
    source = Tokens({"tid": TENANT.upper(), "oid": USER_OID.upper()})
    bound = AccountBoundTokenSource(source, Account(TENANT, USER_OID, None))

    token = bound.get_token("outlook.graph")

    assert token.profile == "outlook.graph"
    assert source.profiles == ["outlook.graph"]
    assert bound.sign_in_command("outlook.graph") == "connector auth outlook.graph"


@pytest.mark.parametrize(
    "claims",
    [
        {"tid": TENANT, "oid": OTHER_OID},
        {"tid": TENANT},
        {},
    ],
)
def test_account_bound_source_rejects_tokens_without_the_service_identity(
    claims: dict[str, str],
) -> None:
    bound = AccountBoundTokenSource(Tokens(claims), Account(TENANT, USER_OID, None))

    with pytest.raises(AccountMismatch):
        bound.get_token("teams.graph")
