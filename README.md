# lrh-m365-auth

Shared Microsoft sign-in for the local Outlook, Teams, and SharePoint connectors. The library
keeps each product's client/resource profile in one encrypted MSAL cache under the same Windows
user profile. Any connector's explicit `auth` command checks every supported profile, silently
reuses accepted credentials, and requests device-code approval only for a profile that needs it.
Microsoft can still require more than one approval because the connectors use different public
clients and resource audiences.

The `outlook.graph` profile requests delegated Graph `Mail.Read` and `User.Read`: mailbox reads use
the former, while Outlook's signed-in profile and photo use the latter. The additional profile
permission does not establish access to OneDrive or SharePoint files.

The cache is for one active Microsoft account. Switching accounts requires the connector's
`auth --sign-out` command followed by `auth`; the account-state marker makes already-running
processes discard in-memory tokens on their next acquisition. Encryption is mandatory by default.

Connectors bind the token source used by a service context to that context's account. If another
process switches accounts, later API requests from the old context fail with an account mismatch
instead of mixing the new account's remote data with the old account's local store.

This package does not make Microsoft Graph, Outlook, or Teams requests. It does not exchange Teams
tokens for a Chat Service session, read browser cookies, run a daemon, or refresh tokens in the
background.

## Development

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Tests use synthetic accounts and fake identity-provider responses. They never contact Microsoft.
