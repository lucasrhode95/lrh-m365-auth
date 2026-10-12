from m365_auth import PROFILES


def test_outlook_graph_profile_requests_mail_and_signed_in_profile_permissions() -> None:
    assert PROFILES["outlook.graph"].scopes == (
        "https://graph.microsoft.com/Mail.Read",
        "https://graph.microsoft.com/User.Read",
    )
