from __future__ import annotations

from multiprocessing import get_context
from pathlib import Path
from typing import Any

from m365_auth import PROFILES, TokenProvider
from tests.msal_fakes import USER_OID, msal_account, seed_cache, token_result

GRAPH = "https://graph.microsoft.com"
GRAPH_CLIENT = PROFILES["outlook.graph"].client_id


class _SilentApp:
    def __init__(self, token_cache: Any) -> None:
        self._token_cache = token_cache

    def get_accounts(self) -> list[dict[str, str]]:
        return [msal_account()]

    def acquire_token_silent_with_error(
        self, scopes: list[str], account: dict[str, str], **_: Any
    ) -> dict[str, Any]:
        seed_cache(self._token_cache, client_id=GRAPH_CLIENT, scope=f"{GRAPH}/Mail.Read")
        return token_result(aud=GRAPH, scp="Mail.Read")


class _SilentAppFactory:
    def __call__(self, _client_id: str, *, authority: str, token_cache: Any) -> _SilentApp:
        return _SilentApp(token_cache)


def _acquire_token(cache_path: str, start_barrier: Any, results: Any) -> None:
    profiles = {"outlook.graph": PROFILES["outlook.graph"]}
    provider = TokenProvider(
        unsecure=True,
        cache_path=Path(cache_path),
        profiles=profiles,
        app_factory=_SilentAppFactory(),
    )
    start_barrier.wait(timeout=10)
    token = provider.get_token("outlook.graph")
    results.put(token.claims()["oid"])


def test_concurrent_processes_acquire_one_consistent_shared_account(tmp_path: Path) -> None:
    context = get_context("spawn")
    cache_path = tmp_path / "shared-cache.json"
    start_barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(target=_acquire_token, args=(str(cache_path), start_barrier, results))
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=20)

        assert all(process.exitcode == 0 for process in processes)
        assert [results.get(timeout=3) for _ in processes] == [USER_OID, USER_OID]

        provider = TokenProvider(
            unsecure=True,
            cache_path=cache_path,
            profiles={"outlook.graph": PROFILES["outlook.graph"]},
        )
        status = provider.status()
        assert [account.object_id for account in status.accounts] == [USER_OID]
        assert status.profiles[0].signed_in
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join()
        results.close()
