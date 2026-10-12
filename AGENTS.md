# Repository agent instructions

`CLAUDE.md` and `AGENTS.md` must remain identical; change both together.

## Purpose and boundaries

This repository is the shared local authentication library for `lrh-outlook-connector`,
`lrh-teams-connector`, and `lrh-sharepoint-connector`. It is a library, not a daemon. It owns
Microsoft OAuth profiles, one encrypted MSAL cache, account isolation, device-code sign-in,
silent acquisition, status, and sign-out. Product API calls, endpoint payloads, and local data stay
in their owning connector.

All products must use one shared account at a time. Do not add multi-user sessions, background
refresh, schedulers, browser-cookie extraction, or plaintext fallback. Account switches must be
explicit and invalidate memoized tokens in running processes before their next acquisition.

## Implementation rules

- Validate profile names at the public boundary. Internal routines may trust a validated
  `TokenProfile` and must document that assumption.
- Keep encrypted persistence as the default and fail closed when it is unavailable. An explicitly
  requested, isolated development cache may be used only when the caller selects it.
- Persist only non-secret account-state metadata beside the encrypted cache. Never log or commit
  credentials, access/refresh tokens, session cookies, private account names or identifiers.
- Protect cache refresh, sign-in completion, account-state changes and sign-out across processes.
  Do not hold a cache lock while waiting for device-code approval.
- Preserve user/account boundaries; never silently switch or merge accounts.
- No compatibility shims, old-cache readers, automatic migrations, aliases, or plaintext fallback.
  Mechanical one-time cache copying is handled outside this repository.
- Tests use synthetic identities and fake MSAL responses only.

## Checks

Run all checks before every commit:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```
