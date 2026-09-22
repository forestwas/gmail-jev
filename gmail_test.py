import os

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from workflow import SCOPES


def main():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file(
            "token.json",
            SCOPES,
        )

    if not creds or not creds.valid:
        refreshed = False

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except RefreshError:
                creds = None

        if not refreshed and (not creds or not creds.valid):
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds)

    profile = service.users().getProfile(userId="me").execute()

    print("Connected as:", profile["emailAddress"])
    print("Messages:", profile["messagesTotal"])
    print("Threads:", profile["threadsTotal"])
    print("Saved token.json for later runs.")


if __name__ == "__main__":
    main()
