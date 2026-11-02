from m365_auth import PROFILES


def test_outlook_graph_profile_requests_mail_and_signed_in_profile_permissions() -> None:
    assert PROFILES["outlook.graph"].scopes == (
        "https://graph.microsoft.com/Mail.Read",
        "https://graph.microsoft.com/User.Read",
    )


def test_microsoft_365_search_profile_uses_the_separately_verified_search_resource() -> None:
    profile = PROFILES["m365.search"]
    assert profile.client_id == PROFILES["outlook.api"].client_id
    assert profile.scopes == ("https://outlook.office.com/search/.default",)


def test_outlook_calendar_profile_reads_calendars_on_the_teams_client_under_its_own_name() -> None:
    profile = PROFILES["outlook.calendar"]
    assert profile.client_id == PROFILES["teams.graph"].client_id
    assert profile.scopes == ("https://graph.microsoft.com/Calendars.Read",)
