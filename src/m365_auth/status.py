"""Status of the shared sign-in, in one shape for every connector.

``status_report`` is the offline view behind each connector's ``auth_status`` MCP tool and makes no
network call. ``status_lines`` renders the same data for a terminal, and ``check_profiles`` is the online
check behind ``status --check``. Nothing here prints, and no token value leaves this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from m365_auth.errors import AuthError
from m365_auth.tokens import TokenProvider


def status_report(provider: TokenProvider) -> dict[str, Any]:
    """Offline: the signed-in account, each profile's cached credential and expiry, and how to sign in."""
    status = provider.status()
    return {
        "account": [account.username for account in status.accounts],
        "profiles": {
            profile.profile: {
                "purpose": profile.purpose,
                "client_credential_cached": profile.client_credential_cached,
                "access_token_expires_on": _iso(profile.access_token_expires_on),
            }
            for profile in status.profiles
        },
        "sign_in_command": provider.sign_in_command(),
    }


def check_profiles(provider: TokenProvider) -> dict[str, dict[str, object]]:
    """Online: try each profile's token silently. This checks token acquisition, not access to any service."""
    checks: dict[str, dict[str, object]] = {}
    for name in provider.profile_names:
        try:
            token = provider.get_token(name)
        except AuthError as exc:
            checks[name] = {"ok": False, "error": str(exc)}
        else:
            checks[name] = {"ok": True, "source": token.source}
    return checks


def status_lines(
    provider: TokenProvider, checks: Mapping[str, Mapping[str, object]] | None = None
) -> list[str]:
    """The status as terminal text; ``checks`` (from ``check_profiles``) adds each profile's result."""
    status = provider.status()
    lines = [f"Token cache: {status.mode}, {status.path}" + ("" if status.exists else " (not created yet)")]
    if not status.accounts:
        lines.append("Account:     not signed in")
    for account in status.accounts:
        lines.append(f"Account:     {account.username} (fingerprint {account.fingerprint})")
    for profile in status.profiles:
        state = "cached" if profile.client_credential_cached else "not cached"
        lines += [
            "",
            f"[{profile.profile}] {profile.purpose}",
            f"  client {profile.client_id} -> {' '.join(profile.scopes)}",
            f"  client credential {state}; access token valid until "
            f"{_iso(profile.access_token_expires_on) or '-'}",
        ]
        if checks and profile.profile in checks:
            check = checks[profile.profile]
            if check["ok"]:
                lines.append(
                    f"  check: token acquisition ok ({check['source']}); not a service-permission test"
                )
            else:
                lines.append(f"  check: FAILED - {check['error']}")
    return lines


def _iso(epoch: int | None) -> str | None:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds") if epoch else None
