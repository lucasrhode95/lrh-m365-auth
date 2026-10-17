from __future__ import annotations

from pathlib import Path

from m365_auth import PROFILES, check_profiles, status_lines, status_report
from tests.msal_fakes import Script, seed_cache
from tests.test_tokens import GRAPH_CLIENT, provider


def test_report_lists_every_profile_offline_and_names_the_sign_in(tmp_path: Path) -> None:
    script = Script()
    report = status_report(provider(script, tmp_path))

    assert report["account"] == []
    assert list(report["profiles"]) == list(PROFILES)
    assert report["sign_in_command"] == "outlook-connector auth --unsecure"
    assert script.created == [] and script.silent_options == []  # no token was requested


def test_report_shows_the_signed_in_account_and_cached_credentials(tmp_path: Path) -> None:
    auth = provider(Script(), tmp_path)
    seed_cache(auth._cache(), client_id=GRAPH_CLIENT, scope="https://graph.microsoft.com/Mail.Read")

    report = status_report(auth)

    assert report["account"] == ["user@example.com"]
    assert report["profiles"]["outlook.graph"]["client_credential_cached"] is True
    assert report["profiles"]["outlook.graph"]["access_token_expires_on"] is not None
    assert "eyJ" not in str(report)  # no token value appears in the report


def test_text_status_names_each_profile_and_its_check(tmp_path: Path) -> None:
    lines = status_lines(provider(Script(), tmp_path), {"outlook.graph": {"ok": False, "error": "synthetic"}})
    text = "\n".join(lines)

    assert "Account:     not signed in" in text
    assert "[outlook.graph]" in text and "check: FAILED - synthetic" in text


def test_checks_report_a_refused_profile_without_raising(tmp_path: Path) -> None:
    script = Script()  # no account and no silent result: every profile needs a sign-in
    checks = check_profiles(provider(script, tmp_path))

    assert set(checks) == set(PROFILES)
    assert all(check["ok"] is False and "sign-in" in str(check["error"]).lower() for check in checks.values())
