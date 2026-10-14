# Shared sign-in research

Dated evidence about Microsoft sign-in for the `lrh-*` connectors: which Microsoft-owned public clients are granted which permissions, and how consent behaves. It decides the profile catalog in this package. Results are tenant- and account-specific; re-check them before relying on them in another environment.

## Microsoft client and scope grants (2026-10-01 to 2026-10-11)

The [MSAL token-acquisition guide](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens)
describes the public authentication flow. The evidence below establishes which Microsoft-owned
clients are preauthorized in this tenant; those grants cannot be inferred from Graph's permission
reference alone. Probes used the `organizations` authority.

| Client | Resource / scope | Result |
|---|---|---|
| **C** Outlook Mobile `27922004-5251-4030-b22d-91ecd9a37ea4` | Graph `Mail.Read` (`.default`: 18 scopes) | **Granted.** The only mail scopes are `Mail.Read` and `Mail.Read.Shared`. Silent refresh works. The set also includes `User.Read` (checked 2026-10-04): `/me` and `/me/photos/48x48/$value` work with this sign-in, so the UI shows the user's name and photo without new permissions. |
| C | Graph `Mail.Send`, `Mail.ReadWrite`, `Mail.ReadWrite.Shared` | **Denied: AADSTS65002** |
| **A** One Outlook Web `9199bf20-a13f-4107-85dc-02114787ef48` | `https://outlook.office.com/.default` | **Granted.** Includes `Mail.ReadWrite(.All/.Shared)` and `Mail.Send(.Shared)` for the Outlook resource. |
| A | `https://outlook.office.com/search/.default` | **Granted** silently from A's refresh token. Audience `66a88757-258c-4c72-893c-3e8bed4d6899`, scope `SubstrateSearch-Internal.ReadWrite`. This is the same client and scope Outlook Web uses (BROWSER). |
| A | Graph `Mail.Read`, `Mail.ReadWrite`, `Mail.Send` (`.default`: 26 scopes, none `Mail.*`) | **Denied: AADSTS65002** |
| **B** Outlook desktop / M365 `d3590ed6-52b3-4102-aeff-aad2292ab01c` | Graph `Mail.Read` | **Denied: AADSTS65002** |
| D older Outlook Web `bc59ab01-8403-45c6-8796-ac3ef710b3e3` | — | Not tested |

- [`AADSTS65002`](https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes) means the client is not preauthorized for that resource. The recorded denial applies to the tested client/resource configuration at that time. The production baseline preserves its denied pairs; portable probes skip only pairs configured locally for the current environment.
- **Conclusion for the tested environment:** none of the tested usable clients could write mail through Graph. The Graph/OWS split in [Outlook connector architecture §6](https://github.com/lucasrhode95/lrh-outlook-connector/blob/main/docs/architecture.md#6-capability-routing-and-portability) follows from this table and must be re-derived for another tenant.

**Shared profile contract (2026-10-11):** `lrh-m365-auth` now explicitly requests Graph `Mail.Read`
and `User.Read` in `outlook.graph`. This preserves the mailbox reads and the `/me` profile and photo
capabilities that were previously verified with the broader granted token above. Microsoft documents
[`User.Read` as the least-privileged delegated permission for the signed-in profile](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0).
For [reading a user's photo](https://learn.microsoft.com/en-us/graph/api/profilephoto-get?view=graph-rest-1.0),
the permission reference lists `ProfilePhoto.Read.All` as least privileged and `User.Read` as an
accepted higher delegated permission. On 2026-10-11, silent token acquisition through the
consolidated profile and live `/me` profile/photo reads succeeded from the existing shared cache
without a device-code flow. This validates the existing account's grants, not a fresh account's
consent outcome.
