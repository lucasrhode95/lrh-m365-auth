"""Cross-process-safe silent token acquisition and explicit device-code sign-in."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import msal
from msal_extensions import CrossPlatLock, FilePersistence, PersistedTokenCache, build_encrypted_persistence

from m365_auth.errors import (
    AccountMismatch,
    AuthConfigurationError,
    AuthenticationRequired,
    AuthError,
    AuthUpstream,
    SecureStorageUnavailable,
)
from m365_auth.models import AccessToken, Account, BootstrapResult, CacheStatus, ProfileStatus
from m365_auth.profiles import AUTHORITY, DENIED_PAIRS, PROFILES, TokenProfile

_REJECTED = {"invalid_grant", "interaction_required", "login_required", "consent_required", "access_denied"}
_NETWORK_RETRIES = 3
_MEMO_MARGIN_SECONDS = 300
_ACCOUNT_STATE_NAME = "account-state.json"
_DEV_ACCOUNT_STATE_NAME = "account-state.plaintext-dev.json"
AppFactory = Callable[..., Any]


@dataclass(frozen=True)
class _AccountState:
    generation: str
    identity_hash: str | None


class TokenProvider:
    """Shared provider for the named connector profiles.

    Profile names and cache paths are validated/configured at this public boundary. Internal
    methods receive a validated `TokenProfile`; they do not reinterpret caller input.
    """

    def __init__(
        self,
        *,
        unsecure: bool = False,
        cache_path: Path | None = None,
        profiles: Mapping[str, TokenProfile] | None = None,
        authority: str | None = None,
        login_command: str = "m365-connector auth",
        app_factory: AppFactory | None = None,
    ) -> None:
        self.unsecure = unsecure
        root = _data_dir()
        self.cache_path = cache_path or root / (
            "token-cache.plaintext-dev.json" if unsecure else "token-cache.bin"
        )
        self.state_path = self.cache_path.parent / (
            _DEV_ACCOUNT_STATE_NAME if unsecure else _ACCOUNT_STATE_NAME
        )
        self.profiles = dict(PROFILES if profiles is None else profiles)
        self.authority = authority or os.environ.get("M365_AUTH_AUTHORITY", AUTHORITY)
        self.login_command = login_command
        self._app_factory = app_factory or msal.PublicClientApplication
        self._apps: dict[str, Any] = {}
        self._token_cache: PersistedTokenCache | None = None
        self._memo: dict[str, tuple[AccessToken, str, str]] = {}
        self._observed_generation: str | None = None

        for profile in self.profiles.values():
            denied = [scope for scope in profile.scopes if (profile.client_id, scope) in DENIED_PAIRS]
            if denied:
                raise AuthConfigurationError(
                    f"Profile '{profile.name}' requests a client/scope pair that Microsoft denied: {denied}."
                )

    @property
    def mode(self) -> str:
        return "plaintext-development" if self.unsecure else "encrypted"

    @property
    def profile_names(self) -> tuple[str, ...]:
        return tuple(self.profiles)

    def sign_in_command(self, profile: str | None = None) -> str:
        """Return this connector's one shared-auth entry point."""
        return self.login_command + (" --unsecure" if self.unsecure else "")

    def get_token(
        self,
        profile: str,
        *,
        force_refresh: bool = False,
        claims_challenge: str | None = None,
    ) -> AccessToken:
        """Acquire silently, checking the shared account generation before any memo is returned."""
        spec = self._profile(profile)
        reuse = not force_refresh and claims_challenge is None
        with self._lock():
            state = self._read_state()
            self._observe_state(state)
            memo = self._memo.get(profile)
            if (
                reuse
                and memo is not None
                and state.identity_hash == memo[1]
                and state.generation == memo[2]
                and self.cache_path.exists()
                and memo[0].expires_on
                and memo[0].expires_on - time.time() > _MEMO_MARGIN_SECONDS
            ):
                return replace(memo[0], source="memory")
            self._memo.pop(profile, None)

            app = self._retry(lambda: self._app(spec))
            account_rows = app.get_accounts()
            account = self._bound_account(account_rows)
            if account is None:
                raise AuthenticationRequired(
                    f"No Microsoft sign-in found for '{profile}'.", command=self.sign_in_command()
                )
            state = self._bind_account(account, state)
            options: dict[str, Any] = {}
            if force_refresh:
                options["force_refresh"] = True
            if claims_challenge:
                options["claims_challenge"] = claims_challenge
            result = self._retry(
                lambda: app.acquire_token_silent_with_error(
                    list(spec.scopes), account=self._msal_account(account_rows, account), **options
                )
            )
            token = self._token_from_result(profile, result)
            self._validate_result_account(result, token, account)
            self._memo[profile] = (token, account.identity_hash, state.generation)
            return token

    def sign_in(self, profile: str, *, show: Callable[[str], None] = print) -> AccessToken:
        """Complete one profile's device-code flow without locking while a person approves it."""
        spec = self._profile(profile)
        with self._lock():
            state = self._read_state()
            self._observe_state(state)
            app = self._retry(lambda: self._app(spec))
            existing = self._bound_account(app.get_accounts())
            if existing is not None:
                state = self._bind_account(existing, state)
            elif state.identity_hash is not None:
                raise AccountMismatch(
                    "The shared auth state still binds another account. Run "
                    f"`{self.sign_in_command()} --sign-out` before signing in again."
                )
            starting_generation = state.generation

        flow = self._retry(lambda: app.initiate_device_flow(scopes=list(spec.scopes)))
        if not isinstance(flow, dict) or "user_code" not in flow:
            raise AuthUpstream(f"Microsoft did not start device-code sign-in: {_error_text(flow)}")
        show(str(flow.get("message", "")))
        result = app.acquire_token_by_device_flow(flow)
        if isinstance(result, dict) and result.get("error") in ("authorization_pending", "expired_token"):
            raise AuthenticationRequired(
                "The sign-in code expired before it was used.", command=self.sign_in_command()
            )
        token = self._token_from_result(profile, result)
        signed_in = _account_from_result(result)
        if signed_in is None:
            raise AuthUpstream("Microsoft sign-in returned no stable tenant and user identity.")
        self._validate_result_account(result, token, signed_in)

        with self._lock():
            current_state = self._read_state()
            self._observe_state(current_state)
            if (
                current_state.generation != starting_generation
                and current_state.identity_hash != signed_in.identity_hash
            ):
                self._remove_account(app, signed_in)
                raise AccountMismatch(
                    "The shared account changed while Microsoft sign-in was waiting for approval. "
                    "Retry the shared auth command."
                )
            cached_accounts = app.get_accounts()
            try:
                cached = self._bound_account(cached_accounts)
            except AccountMismatch:
                self._remove_account(app, signed_in)
                raise
            if cached is None or cached.identity_hash != signed_in.identity_hash:
                self._remove_account(app, signed_in)
                raise AccountMismatch(
                    "The signed-in account was not the single account committed to the shared token cache. "
                    f"Run `{self.sign_in_command()} --sign-out` and try again."
                )
            if current_state.identity_hash not in (None, signed_in.identity_hash):
                self._remove_account(app, signed_in)
                raise AccountMismatch(
                    "The shared auth cache is bound to a different Microsoft account. Run "
                    f"`{self.sign_in_command()} --sign-out` before switching accounts."
                )
            generation = current_state.generation or uuid.uuid4().hex
            if current_state.identity_hash != signed_in.identity_hash:
                generation = uuid.uuid4().hex
            state = _AccountState(generation, signed_in.identity_hash)
            self._write_state(state)
            self._observed_generation = state.generation
            self._memo[profile] = (token, signed_in.identity_hash, state.generation)
            return token

    def bootstrap(self, *, show: Callable[[str], None] = print) -> tuple[BootstrapResult, ...]:
        """Prepare every shared profile, prompting only when silent acquisition needs consent."""
        results: list[BootstrapResult] = []
        interactive_allowed = True
        for name in self.profile_names:
            try:
                token = self.get_token(name)
            except AuthenticationRequired:
                if not interactive_allowed:
                    results.append(
                        BootstrapResult(
                            name,
                            None,
                            AuthenticationRequired(
                                f"No accepted sign-in is available for '{name}'.",
                                command=self.sign_in_command(),
                            ),
                        )
                    )
                    continue
                try:
                    token = self.sign_in(name, show=show)
                except AuthError as exc:
                    results.append(BootstrapResult(name, None, exc))
                    interactive_allowed = False
                    continue
            except AuthError as exc:
                results.append(BootstrapResult(name, None, exc))
                continue
            results.append(BootstrapResult(name, token, None))
        return tuple(results)

    def sign_out(self) -> bool:
        """Invalidate this and other processes' memoized tokens and remove the shared cache."""
        with self._lock():
            state = self._read_state()
            existed = self.cache_path.exists() or state.identity_hash is not None
            self._write_state(_AccountState(uuid.uuid4().hex, None))
            self._apps.clear()
            self._memo.clear()
            self._token_cache = None
            self._observed_generation = None
            self.cache_path.unlink(missing_ok=True)
            return existed

    def status(self) -> CacheStatus:
        """Read cache facts without network access or token values.

        Client credential presence is client-wide, so profiles sharing one OAuth client can
        report the same value. Access-token expiry is resource-specific. Neither field proves
        that Microsoft will issue a token or authorize a service request; ``get_token`` checks
        token acquisition, and the owning connector checks service access.
        """
        with self._lock():
            exists = self.cache_path.exists()
            cache = self._cache() if exists else msal.TokenCache()
            account_rows = cache.search(msal.TokenCache.CredentialType.ACCOUNT)
            accounts = tuple(self._account_or_error(row) for row in account_rows)
            bound = self._bound_account_rows(accounts)
            state = self._read_state()
            if bound is not None and state.identity_hash not in (None, bound.identity_hash):
                raise AccountMismatch("The encrypted token cache and active-account marker do not match.")

            now = time.time()
            rows: list[ProfileStatus] = []
            for spec in self.profiles.values():
                refresh = list(
                    cache.search(
                        msal.TokenCache.CredentialType.REFRESH_TOKEN, query={"client_id": spec.client_id}
                    )
                )
                resources = {_resource(scope) for scope in spec.scopes}
                expiries = [
                    int(entry.get("expires_on", 0))
                    for entry in cache.search(
                        msal.TokenCache.CredentialType.ACCESS_TOKEN, query={"client_id": spec.client_id}
                    )
                    if int(entry.get("expires_on", 0)) > now
                    and any(resource in str(entry.get("target", "")).lower() for resource in resources)
                ]
                rows.append(
                    ProfileStatus(
                        spec.name,
                        spec.client_id,
                        spec.scopes,
                        spec.purpose,
                        client_credential_cached=bool(refresh),
                        access_token_expires_on=max(expiries) if expiries else None,
                    )
                )
            return CacheStatus(self.mode, self.cache_path, exists, accounts, tuple(rows))

    def cached_account(self) -> Account | None:
        """Return the one bound account from the cache, without contacting Microsoft."""
        with self._lock():
            if not self.cache_path.exists():
                return None
            accounts = self._cache().search(msal.TokenCache.CredentialType.ACCOUNT)
            account = self._bound_account(accounts)
            if account is None:
                return None
            self._bind_account(account, self._read_state())
            return account

    def _profile(self, name: str) -> TokenProfile:
        try:
            return self.profiles[name]
        except KeyError:
            raise AuthConfigurationError(
                f"Unknown auth profile '{name}'. Known: {sorted(self.profiles)}"
            ) from None

    def _app(self, spec: TokenProfile) -> Any:
        if spec.client_id not in self._apps:
            if self._token_cache is None:
                self._token_cache = self._cache()
            self._apps[spec.client_id] = self._app_factory(
                spec.client_id, authority=self.authority, token_cache=self._token_cache
            )
        return self._apps[spec.client_id]

    def _cache(self) -> PersistedTokenCache:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        if self.unsecure:
            return PersistedTokenCache(FilePersistence(str(self.cache_path)))
        try:
            persistence = build_encrypted_persistence(str(self.cache_path))
        except Exception as exc:
            raise SecureStorageUnavailable(
                f"Encrypted token storage is unavailable ({type(exc).__name__}). "
                "No plaintext cache will be used."
            ) from None
        return PersistedTokenCache(persistence)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with CrossPlatLock(f"{self.cache_path}.acquire.lock"):
            yield

    def _read_state(self) -> _AccountState:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _AccountState("", None)
        except (OSError, json.JSONDecodeError):
            raise AuthConfigurationError(
                "The shared account-state file cannot be read; sign-in is blocked."
            ) from None
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("generation"), str)
            or not data["generation"]
            or (data.get("identity_hash") is not None and not isinstance(data.get("identity_hash"), str))
        ):
            raise AuthConfigurationError("The shared account-state file is malformed; sign-in is blocked.")
        identity_hash = data.get("identity_hash")
        return _AccountState(data["generation"], identity_hash)

    def _write_state(self, state: _AccountState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f"{self.state_path.name}.{uuid.uuid4().hex}.tmp")
        payload = json.dumps({"generation": state.generation, "identity_hash": state.identity_hash})
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _observe_state(self, state: _AccountState) -> None:
        if self._observed_generation is not None and state.generation != self._observed_generation:
            self._apps.clear()
            self._token_cache = None
            self._memo.clear()
        self._observed_generation = state.generation

    def _bind_account(self, account: Account, state: _AccountState) -> _AccountState:
        if state.identity_hash is not None and state.identity_hash != account.identity_hash:
            raise AccountMismatch(
                "The shared Microsoft token cache belongs to a different account. Run "
                f"`{self.sign_in_command()} --sign-out` before switching accounts."
            )
        if state.identity_hash is None:
            state = _AccountState(state.generation or uuid.uuid4().hex, account.identity_hash)
            self._write_state(state)
            self._observed_generation = state.generation
        elif not state.generation:
            state = _AccountState(uuid.uuid4().hex, account.identity_hash)
            self._write_state(state)
            self._observed_generation = state.generation
        return state

    def _bound_account(self, rows: Iterable[dict[str, Any]]) -> Account | None:
        accounts = tuple(self._account_or_error(row) for row in rows)
        return self._bound_account_rows(accounts)

    def _msal_account(self, rows: Iterable[dict[str, Any]], expected: Account) -> dict[str, Any]:
        """Return MSAL's original account row matching the validated shared identity.

        Internal service code uses the small `Account` model, while MSAL's silent-acquisition API
        requires the original dictionary returned by `get_accounts()`.
        """
        for row in rows:
            if self._account_or_error(row).identity_hash == expected.identity_hash:
                return row
        raise AuthConfigurationError("The selected Microsoft account disappeared from the token cache.")

    def _bound_account_rows(self, accounts: tuple[Account, ...]) -> Account | None:
        identities = {account.identity_hash for account in accounts}
        if len(identities) > 1:
            raise AccountMismatch(
                "The shared token cache holds more than one Microsoft account. Run "
                f"`{self.sign_in_command()} --sign-out` and sign in again with one account."
            )
        return accounts[0] if accounts else None

    @staticmethod
    def _account_or_error(row: dict[str, Any]) -> Account:
        try:
            return Account.from_msal(row)
        except ValueError:
            raise AuthConfigurationError(
                "The token cache contains an account without a stable identity."
            ) from None

    def _remove_account(self, app: Any, account: Account) -> None:
        for row in app.get_accounts():
            cached = self._account_or_error(row)
            if cached.identity_hash == account.identity_hash:
                app.remove_account(row)

    def _token_from_result(self, profile: str, result: Any) -> AccessToken:
        if isinstance(result, dict) and result.get("access_token"):
            expires_in = result.get("expires_in")
            return AccessToken(
                profile=profile,
                value=result["access_token"],
                source=str(result.get("token_source", "cache")),
                expires_on=int(time.time() + int(expires_in)) if expires_in else None,
            )
        error = str(result.get("error", "")) if isinstance(result, dict) else ""
        if not result:
            raise AuthenticationRequired(f"No sign-in yet for '{profile}'.", command=self.sign_in_command())
        if error in _REJECTED:
            raise AuthenticationRequired(
                f"Microsoft no longer accepts the stored sign-in for '{profile}' ({_error_text(result)}).",
                command=self.sign_in_command(),
            )
        raise AuthUpstream(f"Token request for '{profile}' failed: {_error_text(result)}")

    def _validate_result_account(self, result: Any, token: AccessToken, expected: Account) -> None:
        response_account = _account_from_result(result) if isinstance(result, dict) else None
        token_claims = token.claims()
        token_account = None
        if token_claims.get("tid") and token_claims.get("oid"):
            token_account = Account(
                tenant_id=str(token_claims["tid"]),
                object_id=str(token_claims["oid"]),
                username=token_claims.get("preferred_username") or token_claims.get("upn"),
            )
        for candidate in (response_account, token_account):
            if candidate is not None and candidate.identity_hash != expected.identity_hash:
                raise AccountMismatch("Microsoft returned a token for a different active account.")

    @staticmethod
    def _retry(operation: Callable[[], Any]) -> Any:
        """Retry transient idempotent identity-provider requests."""
        import requests

        for attempt in range(_NETWORK_RETRIES):
            try:
                return operation()
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == _NETWORK_RETRIES - 1:
                    raise AuthUpstream(f"Could not reach Microsoft sign-in ({type(exc).__name__}).") from None
                time.sleep(2**attempt)
        raise AssertionError("unreachable")


def _data_dir() -> Path:
    override = os.environ.get("M365_AUTH_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return Path.home() / ".lrh-m365-auth"
    root = os.environ.get("XDG_DATA_HOME")
    return (Path(root) if root else Path.home() / ".local" / "share") / "lrh-m365-auth"


def _account_from_result(result: Any) -> Account | None:
    claims = result.get("id_token_claims") or {} if isinstance(result, dict) else {}
    if not isinstance(claims, dict) or not claims.get("oid") or not claims.get("tid"):
        return None
    return Account(
        tenant_id=str(claims["tid"]),
        object_id=str(claims["oid"]),
        username=claims.get("preferred_username"),
    )


def _resource(scope: str) -> str:
    if scope.endswith("/.default"):
        return scope.removesuffix("/.default").lower()
    return scope.rsplit("/", 1)[0].lower()


def _error_text(result: Any) -> str:
    if not isinstance(result, dict):
        return "no response"
    codes = result.get("error_codes") or []
    suffix = f" AADSTS{codes[0]}" if codes else ""
    return f"{result.get('error', 'unknown_error')}{suffix}"
