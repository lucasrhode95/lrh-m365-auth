![The Outlook, Teams and SharePoint connectors share one encrypted token cache through lrh-m365-auth, which signs in with Microsoft Entra ID.](https://raw.githubusercontent.com/lucasrhode95/lrh-m365-auth/main/docs/connector-overview.svg)

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

Offline status reports whether each OAuth client has a cached refresh credential and when a
matching resource access token expires, if one is cached. Profiles that share a client can show the
same client-credential state even when only one resource token is cached. `status --check` attempts
token acquisition for each profile; only an operation against the owning service can establish
service access.

The `m365.search` profile requests the separate Outlook-host Search resource used by the verified
Search v2 calendar and Teams-message queries. It uses the same first-party client as `outlook.api`
but has a distinct resource token; approval for one resource does not prove the other is available.

Connectors bind the token source used by a service context to that context's account. If another
process switches accounts, later API requests from the old context fail with an account mismatch
instead of mixing the new account's remote data with the old account's local store.

This package does not make Microsoft Graph, Outlook, or Teams requests. It does not exchange Teams
tokens for a Chat Service session, read browser cookies, run a daemon, or refresh tokens in the
background.

## Microsoft 365 connectors

This repository is part of the `lrh-*` **Microsoft 365** connectors: local tools that give MCP agents
access to a common corporate environment, its mail and calendar, chats and meetings, and files. Each
repository owns one product, and all of them share one sign-in.

<table>
  <tr><th width="270" nowrap>Repository</th><th>Responsible for</th></tr>
  <tr><td nowrap><picture><img src="https://raw.githubusercontent.com/lucasrhode95/lrh-m365-auth/main/docs/logos/entra-id.svg" height="29" align="absmiddle" alt="Entra ID"></picture>&nbsp;<a href="https://github.com/lucasrhode95/lrh-m365-auth">lrh-m365-auth</a></td><td>Shared <b>Microsoft</b> sign-in through <b>Entra ID</b>: one encrypted token cache and the profiles every connector uses</td></tr>
  <tr><td nowrap><picture><img src="https://raw.githubusercontent.com/lucasrhode95/lrh-m365-auth/main/docs/logos/outlook.svg" height="24" align="absmiddle" alt="Outlook"></picture>&nbsp;<a href="https://github.com/lucasrhode95/lrh-outlook-connector">lrh-outlook-connector</a></td><td><b>Exchange</b> mail, folders, drafts, rules, native signatures, and calendar events (schedule, agenda, attendees, <b>Teams</b> join link)</td></tr>
  <tr><td nowrap><picture><img src="https://raw.githubusercontent.com/lucasrhode95/lrh-m365-auth/main/docs/logos/teams.svg" height="24" align="absmiddle" alt="Teams"></picture>&nbsp;<a href="https://github.com/lucasrhode95/lrh-teams-connector">lrh-teams-connector</a></td><td><b>Teams</b> chats and channels, message attachments, and meeting chats, recordings, transcripts, recaps and notes</td></tr>
  <tr><td nowrap><picture><img src="https://raw.githubusercontent.com/lucasrhode95/lrh-m365-auth/main/docs/logos/sharepoint.svg" height="24" align="absmiddle" alt="SharePoint"></picture>&nbsp;<a href="https://github.com/lucasrhode95/lrh-sharepoint-connector">lrh-sharepoint-connector</a></td><td>General <b>OneDrive</b> and <b>SharePoint</b> file search and selected file retrieval (read-only)</td></tr>
</table>

A calendar event stays with **Outlook** even when it links to a **Teams** meeting; **Teams** owns that
meeting's chat and artifacts. A file linked from an email or a **Teams** message stays part of that
message, while the stored file itself is retrieved through **SharePoint**. Only verified identifiers
connect records across products.

## Development

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Tests use synthetic accounts and fake identity-provider responses. They never contact Microsoft.

Project references: [documentation index](docs/README.md) · [sign-in research](docs/api-research.md).

## Disclaimer

> [!WARNING]
> Unofficial: these tools sign in as Microsoft's own apps and use undocumented services. Check your
> organization's AI and data policies before giving an agent your work data. Provided as is, without
> warranty. Microsoft, Outlook, Teams, SharePoint and Entra are Microsoft trademarks; this project is
> not affiliated with Microsoft.

## License

Copyright 2026 Lucas Rhode. This is source-available software, not open source: the code is public
so anyone can read and audit it. The [PolyForm Internal Use License 1.0.0](LICENSE.md) lets you and
your company use and adapt the software for your own internal operations, including at work. The
licensor also permits personal, noncommercial use. Serving other companies with it is not internal
use: you may not sell it, ship it in a product, or offer it as a service, and you may not distribute
the software or a modified copy of it.
