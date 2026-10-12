"""Named first-party OAuth clients and resource scopes shared by the connectors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

TENANT = "organizations"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT}"

OUTLOOK_MOBILE_CLIENT_ID = "27922004-5251-4030-b22d-91ecd9a37ea4"
ONE_OUTLOOK_WEB_CLIENT_ID = "9199bf20-a13f-4107-85dc-02114787ef48"
TEAMS_CLIENT_ID = "1fec8e78-bce4-4aaf-ab1b-5451cc387264"


@dataclass(frozen=True)
class TokenProfile:
    """One named client/resource request that yields a distinct access-token audience."""

    name: str
    client_id: str
    scopes: tuple[str, ...]
    purpose: str


PROFILES: Mapping[str, TokenProfile] = MappingProxyType(
    {
        "outlook.graph": TokenProfile(
            "outlook.graph",
            OUTLOOK_MOBILE_CLIENT_ID,
            ("https://graph.microsoft.com/Mail.Read",),
            "Outlook mail reads and previously validated file search through Microsoft Graph",
        ),
        "outlook.api": TokenProfile(
            "outlook.api",
            ONE_OUTLOOK_WEB_CLIENT_ID,
            ("https://outlook.office.com/.default",),
            "Outlook APIs used for mail changes, inbox rules and native signatures",
        ),
        "teams.spaces": TokenProfile(
            "teams.spaces",
            TEAMS_CLIENT_ID,
            ("https://api.spaces.skype.com/.default",),
            "Teams Chat Service session exchange and chat history",
        ),
        "teams.csa": TokenProfile(
            "teams.csa",
            TEAMS_CLIENT_ID,
            ("https://chatsvcagg.teams.microsoft.com/.default",),
            "Teams chat catalog through Chat Service Aggregator",
        ),
        "teams.graph": TokenProfile(
            "teams.graph",
            TEAMS_CLIENT_ID,
            ("https://graph.microsoft.com/.default",),
            "Teams Graph operations including channels, people, photos and sending",
        ),
    }
)


# Client/scope pairs refused with AADSTS65002 in the dated connector research.
DENIED_PAIRS = frozenset(
    {
        ("d3590ed6-52b3-4102-aeff-aad2292ab01c", "https://graph.microsoft.com/Mail.Read"),
        (OUTLOOK_MOBILE_CLIENT_ID, "https://graph.microsoft.com/Mail.Send"),
        (OUTLOOK_MOBILE_CLIENT_ID, "https://graph.microsoft.com/Mail.ReadWrite"),
        (OUTLOOK_MOBILE_CLIENT_ID, "https://graph.microsoft.com/Mail.ReadWrite.Shared"),
        (ONE_OUTLOOK_WEB_CLIENT_ID, "https://graph.microsoft.com/Mail.Read"),
        (ONE_OUTLOOK_WEB_CLIENT_ID, "https://graph.microsoft.com/Mail.ReadWrite"),
        (ONE_OUTLOOK_WEB_CLIENT_ID, "https://graph.microsoft.com/Mail.Send"),
        (TEAMS_CLIENT_ID, "https://graph.microsoft.com/Chat.Read"),
    }
)
