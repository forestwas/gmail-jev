from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

flow = InstalledAppFlow.from_client_secrets_file(
    "credentials.json",
    SCOPES,
)

creds = flow.run_local_server(port=0)

service = build("gmail", "v1", credentials=creds)

profile = service.users().getProfile(userId="me").execute()

print("Connected as:", profile["emailAddress"])
print("Messages:", profile["messagesTotal"])
print("Threads:", profile["threadsTotal"])
