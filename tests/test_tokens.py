from __future__ import annotations

from pathlib import Path

import pytest
import requests

from m365_auth import (
    PROFILES,
    Account,
    AccountMismatch,
    AuthConfigurationError,
    AuthenticationRequired,
    SecureStorageUnavailable,
    TokenProvider,
    tokens,
)
from tests.msal_fakes import (
    OTHER_OID,
    USER_OID,
    FakeAppFactory,
    Script,
    msal_account,
    seed_cache,
    token_result,
)

GRAPH = "https://graph.microsoft.com"
GRAPH_CLIENT = PROFILES["outlook.graph"].client_id
OUTLOOK_CLIENT = PROFILES["outlook.api"].client_id


def provider(script: Script, home: Path, *, profiles=None) -> TokenProvider:
    script.cache_path = home / "token-cache.plaintext-dev.json"
    return TokenProvider(
        unsecure=True,
        cache_path=script.cache_path,
        profiles=profiles,
        login_command="outlook-connector auth",
        app_factory=FakeAppFactory(script),
    )


def test_profile_catalog_covers_all_three_connectors_without_name_collisions() -> None:
    assert tuple(PROFILES) == (
        "outlook.graph",
        "outlook.api",
        "teams.spaces",
        "teams.csa",
        "teams.graph",
    )
    assert len({profile.name for profile in PROFILES.values()}) == len(PROFILES)


def test_unknown_profile_is_rejected_at_the_public_boundary(tmp_path: Path) -> None:
    with pytest.raises(AuthConfigurationError, match="Unknown auth profile"):
        provider(Script(), tmp_path).get_token("graph")


def test_silent_token_is_bound_to_cached_account_and_hidden_from_repr(tmp_path: Path) -> None:
    script = Script(
        accounts=[msal_account()],
        silent={GRAPH_CLIENT: token_result(aud=GRAPH, scp="Mail.Read")},
    )
    token = provider(script, tmp_path).get_token("outlook.graph")
    assert token.profile == "outlook.graph"
    assert token.claims()["aud"] == GRAPH
    assert "value=" not in repr(token)
    assert script.silent_accounts == script.accounts


def test_revoked_refresh_credential_requires_explicit_sign_in(tmp_path: Path) -> None:
    script = Script(accounts=[msal_account()], silent={GRAPH_CLIENT: {"error": "invalid_grant"}})

    with pytest.raises(AuthenticationRequired, match="no longer accepts the stored sign-in"):
        provider(script, tmp_path).get_token("outlook.graph")


def test_valid_memo_is_reused_and_refresh_options_bypass_it(tmp_path: Path) -> None:
    script = Script(
        accounts=[msal_account()],
        silent={GRAPH_CLIENT: [token_result(aud=GRAPH, scp="Mail.Read")] * 3},
    )
    tokens_ = provider(script, tmp_path)
    first, second = tokens_.get_token("outlook.graph"), tokens_.get_token("outlook.graph")
    tokens_.get_token("outlook.graph", force_refresh=True)
    tokens_.get_token("outlook.graph", claims_challenge='{"access_token":{}}')
    assert (first.source, second.source) == ("cache", "memory")
    assert script.silent_options == [{}, {"force_refresh": True}, {"claims_challenge": '{"access_token":{}}'}]


def test_missing_profile_token_returns_the_calling_connectors_login_command(tmp_path: Path) -> None:
    with pytest.raises(AuthenticationRequired) as error:
        provider(Script(), tmp_path).get_token("outlook.graph")
    assert error.value.command == "outlook-connector auth --unsecure"


def test_device_code_sign_in_binds_account_and_shows_identity_message(tmp_path: Path) -> None:
    shown: list[str] = []
    script = Script(device_result=token_result(aud=GRAPH, scp="Mail.Read", source="identity_provider"))
    token = provider(script, tmp_path).sign_in("outlook.graph", show=shown.append)
    assert shown and "ABC123" in shown[0]
    assert token.source == "identity_provider"
    assert Account.from_msal(script.accounts[0]).object_id == USER_OID


def test_sign_in_for_a_different_account_is_removed_and_refused(tmp_path: Path) -> None:
    script = Script(
        accounts=[msal_account(username="bound@example.com")],
        device_result=token_result(
            aud=GRAPH,
            scp="Mail.Read",
            oid=OTHER_OID,
            username="other@example.com",
            source="identity_provider",
        ),
    )
    with pytest.raises(AccountMismatch):
        provider(script, tmp_path).sign_in("outlook.api", show=lambda _message: None)
    assert [row["home_account_id"].split(".")[0] for row in script.removed] == [OTHER_OID]
    assert [row["home_account_id"].split(".")[0] for row in script.accounts] == [USER_OID]


def test_expired_device_code_requires_a_new_explicit_login(tmp_path: Path) -> None:
    script = Script(device_result={"error": "authorization_pending", "error_codes": [70016]})
    with pytest.raises(AuthenticationRequired, match="expired before it was used"):
        provider(script, tmp_path).sign_in("outlook.graph", show=lambda _message: None)


def test_declined_device_code_is_an_identity_service_error(tmp_path: Path) -> None:
    script = Script(device_result={"error": "authorization_declined"})
    with pytest.raises(tokens.AuthUpstream):
        provider(script, tmp_path).sign_in("outlook.graph", show=lambda _message: None)


def test_bootstrap_does_not_start_new_device_flows_after_approval_fails(tmp_path: Path) -> None:
    script = Script(device_result={"error": "authorization_declined"})
    profiles = {name: PROFILES[name] for name in ("outlook.graph", "outlook.api")}
    results = provider(script, tmp_path, profiles=profiles).bootstrap(show=lambda _message: None)
    assert script.shown_flows == 1
    assert [result.ready for result in results] == [False, False]


def test_bootstrap_keeps_ready_profile_when_a_later_profile_is_declined(tmp_path: Path) -> None:
    script = Script(
        accounts=[msal_account()],
        silent={GRAPH_CLIENT: token_result(aud=GRAPH, scp="Mail.Read")},
        device_result={"error": "authorization_declined"},
    )
    profiles = {name: PROFILES[name] for name in ("outlook.graph", "outlook.api")}
    tokens_ = provider(script, tmp_path, profiles=profiles)
    seed_cache(tokens_._cache(), client_id=GRAPH_CLIENT, scope="https://graph.microsoft.com/Mail.Read")

    results = tokens_.bootstrap(show=lambda _message: None)

    assert [result.ready for result in results] == [True, False]
    status = tokens_.status()
    assert status.profiles[0].client_credential_cached
    assert not status.profiles[1].client_credential_cached
    assert script.shown_flows == 1


def test_identity_network_failures_are_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tokens.time, "sleep", lambda _seconds: None)
    script = Script(
        accounts=[msal_account()],
        silent={GRAPH_CLIENT: [requests.ConnectionError(), token_result(aud=GRAPH, scp="Mail.Read")]},
    )
    assert provider(script, tmp_path).get_token("outlook.graph").profile == "outlook.graph"


def test_multiple_accounts_are_refused(tmp_path: Path) -> None:
    script = Script(accounts=[msal_account(), msal_account(oid=OTHER_OID)])
    with pytest.raises(AccountMismatch):
        provider(script, tmp_path).get_token("outlook.graph")


def test_encrypted_storage_failure_does_not_fall_back_to_plaintext(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def unavailable(_path: str) -> object:
        raise RuntimeError("synthetic encryption unavailable")

    monkeypatch.setenv("M365_AUTH_HOME", str(tmp_path))
    monkeypatch.setattr(tokens, "build_encrypted_persistence", unavailable)
    secure = TokenProvider()
    with pytest.raises(SecureStorageUnavailable):
        secure.get_token("outlook.graph")
    assert not (tmp_path / "token-cache.plaintext-dev.json").exists()


def test_status_reads_synthetic_cache_without_network(tmp_path: Path) -> None:
    tokens_ = provider(Script(), tmp_path)
    seed_cache(tokens_._cache(), client_id=GRAPH_CLIENT, scope="https://graph.microsoft.com/Mail.Read")
    status = tokens_.status()
    assert status.exists and status.mode == "plaintext-development"
    assert [account.object_id for account in status.accounts] == [USER_OID]
    profiles = {profile.profile: profile for profile in status.profiles}
    assert profiles["outlook.graph"].client_credential_cached
    assert profiles["outlook.graph"].access_token_expires_on
    assert not profiles["outlook.api"].client_credential_cached
    assert profiles["outlook.api"].access_token_expires_on is None


def test_status_separates_client_credentials_from_resource_tokens(tmp_path: Path) -> None:
    teams_profiles = {name: PROFILES[name] for name in ("teams.spaces", "teams.csa", "teams.graph")}
    tokens_ = provider(Script(), tmp_path, profiles=teams_profiles)
    seed_cache(
        tokens_._cache(),
        client_id=PROFILES["teams.spaces"].client_id,
        scope="https://api.spaces.skype.com/.default",
    )

    profiles = {row.profile: row for row in tokens_.status().profiles}

    assert all(row.client_credential_cached for row in profiles.values())
    assert profiles["teams.spaces"].access_token_expires_on is not None
    assert profiles["teams.csa"].access_token_expires_on is None
    assert profiles["teams.graph"].access_token_expires_on is None


def test_sign_out_invalidates_a_memoized_token_in_another_process(
    tmp_path: Path,
) -> None:
    script = Script(
        accounts=[msal_account()],
        silent={GRAPH_CLIENT: token_result(aud=GRAPH, scp="Mail.Read")},
    )
    first = provider(script, tmp_path)
    assert first.get_token("outlook.graph").claims()["oid"] == USER_OID
    second = provider(script, tmp_path)
    assert second.sign_out() is True
    script.accounts.clear()
    with pytest.raises(AuthenticationRequired):
        first.get_token("outlook.graph")


def test_switch_after_sign_out_reloads_account_in_a_running_provider(tmp_path: Path) -> None:
    script = Script(
        accounts=[msal_account()],
        silent={GRAPH_CLIENT: token_result(aud=GRAPH, scp="Mail.Read")},
    )
    first = provider(script, tmp_path)
    first.get_token("outlook.graph")
    second = provider(script, tmp_path)
    second.sign_out()
    script.accounts.clear()
    script.device_result = token_result(
        aud=GRAPH, scp="Mail.Read", oid=OTHER_OID, username="other@example.com", source="identity_provider"
    )
    second.sign_in("outlook.graph", show=lambda _message: None)
    script.silent[GRAPH_CLIENT] = token_result(
        aud=GRAPH, scp="Mail.Read", oid=OTHER_OID, username="other@example.com"
    )
    token = first.get_token("outlook.graph")
    assert token.claims()["oid"] == OTHER_OID
    assert token.source == "cache"


def test_sign_out_during_device_approval_cannot_restore_the_old_generation(tmp_path: Path) -> None:
    script = Script(device_result=token_result(aud=GRAPH, scp="Mail.Read", source="identity_provider"))
    first = provider(script, tmp_path)
    app = first._app(PROFILES["outlook.graph"])
    complete_flow = app.acquire_token_by_device_flow
    second = provider(script, tmp_path)

    def sign_out_before_completion(flow):
        second.sign_out()
        return complete_flow(flow)

    app.acquire_token_by_device_flow = sign_out_before_completion
    with pytest.raises(AccountMismatch, match="account changed while"):
        first.sign_in("outlook.graph", show=lambda _message: None)
    assert not script.accounts
    assert first._read_state().identity_hash is None


def test_status_fails_closed_when_state_and_encrypted_cache_disagree(tmp_path: Path) -> None:
    tokens_ = provider(Script(), tmp_path)
    seed_cache(tokens_._cache(), client_id=GRAPH_CLIENT, scope="https://graph.microsoft.com/Mail.Read")
    tokens_.state_path.write_text(
        '{"generation":"generation","identity_hash":"different-account"}', encoding="utf-8"
    )
    with pytest.raises(AccountMismatch):
        tokens_.status()
