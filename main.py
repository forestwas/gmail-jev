import os
import json
import socket
import time
from datetime import datetime
import base64

from dotenv import load_dotenv

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from typesafe_sdk import Choice, Noul, Score, TypeSafeClient


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def get_gmail_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file(
            "token.json",
            SCOPES,
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)



GMAIL_RETRY_ATTEMPTS = int(
    os.getenv("GMAIL_RETRY_ATTEMPTS", "6")
)


def is_retryable_http_error(exc):
    status = getattr(exc.resp, "status", None)

    if status in {408, 429, 500, 502, 503, 504}:
        return True

    if status != 403:
        return False

    content = getattr(exc, "content", b"")

    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="ignore")

    content = content.lower()

    return any(
        marker in content
        for marker in (
            "ratelimitexceeded",
            "userratelimitexceeded",
            "quota exceeded",
            "quota",
        )
    )


def gmail_execute(request, operation):
    for attempt in range(GMAIL_RETRY_ATTEMPTS):
        try:
            return request.execute()

        except HttpError as exc:
            if (
                not is_retryable_http_error(exc)
                or attempt == GMAIL_RETRY_ATTEMPTS - 1
            ):
                raise

            error_name = (
                f"HTTP {getattr(exc.resp, 'status', '?')}"
            )

        except (TimeoutError, socket.timeout, OSError) as exc:
            if attempt == GMAIL_RETRY_ATTEMPTS - 1:
                raise

            error_name = type(exc).__name__

        delay = min(2 ** (attempt + 1), 30)

        print(
            f"Gmail {operation} failed with {error_name}; "
            f"retrying in {delay}s "
            f"({attempt + 1}/{GMAIL_RETRY_ATTEMPTS})..."
        )

        time.sleep(delay)

    raise RuntimeError(
        f"Gmail operation failed unexpectedly: {operation}"
    )



def has_calendar_part(payload):
    """Return True when a Gmail MIME tree contains actual calendar data."""
    if not payload:
        return False

    mime_type = (payload.get("mimeType") or "").lower()
    filename = (payload.get("filename") or "").lower()

    if mime_type == "text/calendar" or filename.endswith(".ics"):
        return True

    return any(
        has_calendar_part(part)
        for part in payload.get("parts", [])
    )


def decode_body(payload):
    text_parts = []

    def walk(part):
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")

        if mime_type == "text/plain" and data:
            decoded = base64.urlsafe_b64decode(
                data + "=" * (-len(data) % 4)
            ).decode("utf-8", errors="replace")

            text_parts.append(decoded)

        for child in part.get("parts", []):
            walk(child)

    walk(payload)

    return "\n".join(text_parts).strip()


def get_header(message, name):
    headers = message.get("payload", {}).get("headers", [])

    for header in headers:
        if header["name"].lower() == name.lower():
            return header["value"]

    return ""


load_dotenv()

DRY_RUN = os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "100"))

# Used in Jev prompts so judgments are framed around the mailbox owner,
# not a hardcoded personal name.
OWNER = os.getenv("MAILBOX_OWNER_NAME", "the mailbox owner")


WORKFLOW_LABELS = [
    "01 — Reply",
    "02 — Action Required",
    "03 — Waiting",
    "04 — Clients",
    "05 — Leads",
    "06 — Finance",
    "07 — Calendar",
    "08 — Read Later",
    "09 — System",
    "97 — Other",
    "98 — Review",
]

DEFAULT_GMAIL_QUERY = (
    "in:inbox "
    + " ".join(
        f'-label:"{label_name}"'
        for label_name in WORKFLOW_LABELS
    )
)


KNOWN_CLIENTS_FILE = os.getenv("KNOWN_CLIENTS_FILE", "clients.local.json")


def load_known_clients():
    if not os.path.exists(KNOWN_CLIENTS_FILE):
        return []

    try:
        with open(KNOWN_CLIENTS_FILE, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARNING: Could not load {KNOWN_CLIENTS_FILE}: {exc}")
        return []

    return data.get("clients", [])


def find_known_client_matches(subject, thread_text, participant_headers):
    haystack = "\n".join(
        [
            subject or "",
            thread_text or "",
            participant_headers or "",
        ]
    ).lower()

    matches = []

    for client in KNOWN_CLIENTS:
        domains = [
            value.strip().lower()
            for value in client.get("domains", [])
            if value.strip()
        ]

        keywords = [
            value.strip().lower()
            for value in client.get("keywords", [])
            if value.strip()
        ]

        if any(value in haystack for value in domains + keywords):
            matches.append(client.get("name", "Unknown client"))

    return matches


KNOWN_CLIENTS = load_known_clients()


gmail = get_gmail_service()

jev = TypeSafeClient(
    api_key=os.environ["TYPESAFE_API_KEY"]
)


results = gmail_execute(
    gmail.users().threads().list(
        userId="me",
        q=os.getenv("GMAIL_QUERY", DEFAULT_GMAIL_QUERY),
        maxResults=MAX_RESULTS,
    ),
    "threads.list",
)

threads = results.get("threads", [])

if not threads:
    print("Inbox is empty.")
    raise SystemExit


def prepare_workflow_labels(service):
    existing = gmail_execute(
        service.users().labels().list(
            userId="me"
        ),
        "labels.list",
    ).get("labels", [])

    label_ids = {
        label["name"]: label["id"]
        for label in existing
    }

    for label_name in WORKFLOW_LABELS:
        if label_name in label_ids:
            continue

        if DRY_RUN:
            label_ids[label_name] = f"DRYRUN::{label_name}"
            continue

        created = service.users().labels().create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ).execute()

        label_ids[label_name] = created["id"]

    return label_ids


label_ids = prepare_workflow_labels(gmail)

print("\nWORKFLOW LABELS READY:")
for label_name in WORKFLOW_LABELS:
    print(f"{label_name} -> {label_ids[label_name]}")


for thread_ref in threads:
    thread = gmail_execute(
        gmail.users().threads().get(
            userId="me",
            id=thread_ref["id"],
            format="full",
        ),
        f"threads.get:{thread_ref['id']}",
    )


    conversation = []

    has_calendar_evidence = any(
        has_calendar_part(message.get("payload", {}))
        for message in thread["messages"]
    )

    for message in thread["messages"]:
        conversation.append(
            f"""
    FROM: {get_header(message, "From")}
    TO: {get_header(message, "To")}
    DATE: {get_header(message, "Date")}

    {decode_body(message["payload"])}
    """.strip()
        )

    thread_text = "\n\n--- MESSAGE ---\n\n".join(conversation)

    if len(thread_text) > 20000:
        thread_text = thread_text[:4000] + "\n\n--- TRUNCATED ---\n\n" + thread_text[-16000:]
    state = {
    "subject": get_header(thread["messages"][0], "Subject"),
    "thread": thread_text,
    }

    participant_headers = "\n".join(
        " ".join(
            filter(
                None,
                [
                    get_header(message, "From"),
                    get_header(message, "To"),
                    get_header(message, "Cc"),
                ],
            )
        )
        for message in thread["messages"]
    )

    known_client_matches = find_known_client_matches(
        state["subject"],
        thread_text,
        participant_headers,
    )


    try:
        result = jev.system_one(
            state=state,
            questions={
                "relationship": Choice(
                    instructions=(
                        f"What is {OWNER}'s relationship to this thread? "
                        "Classify the business or personal relationship, not the message format."
                    ),
                    criteria={
                        "client": (
                            f"An existing paid client or active client project where {OWNER} is providing "
                            "professional services. This can include project-tool notifications tied to that client. "
                            f"Do NOT classify companies {OWNER} buys from, merchants, SaaS providers, vendors, "
                            f"subscription services, invoices sent to {OWNER}, purchases, receipts, orders, "
                            f"shipments, or other businesses where {OWNER} is the customer as clients."
                        ),
                        "lead": (
                            f"A real potential buyer of {OWNER}'s professional services, a concrete project inquiry, "
                            f"business introduction, or partnership opportunity directed specifically to {OWNER}. "
                            "Do NOT classify newsletters, webinars, conferences, promotions, generic sales outreach, "
                            f"job alerts, marketing invitations, or companies trying to sell something to {OWNER} as leads."
                        ),
                        "personal": (
                            f"A direct personal human conversation unrelated to {OWNER}'s professional work."
                        ),
                        "other": (
                            "No active client, genuine sales lead, or personal relationship applies. "
                            f"This includes vendors, merchants, services {OWNER} subscribes to, ecommerce purchases, "
                            "job application systems, newsletters, and most automated service relationships."
                        ),
                    },
                ),

                "message_type": Choice(
                    instructions="What kind of email is this primarily?",
                    criteria={
                        "human_message": (
                            "A normal person-to-person email or project conversation. "
                            "This includes humans discussing availability, proposing meeting times, "
                            "asking when someone is free, or coordinating a meeting by email. "
                            "Do not classify ordinary scheduling conversation as calendar unless "
                            "the message is an actual calendar invitation or calendar-system event."
                        ),
                        "finance": (
                            "Invoice, receipt, failed payment, billing, subscription payment, "
                            "tax, banking, accounting, insurance, insurance policy, premium, "
                            "policy renewal, financial document, or financial administration."
                        ),
                        "calendar": (
                            "An actual calendar invitation or calendar-system event such as an RSVP, "
                            "event update, reschedule, cancellation, or automated calendar reminder. "
                            "A normal human email merely discussing when to meet is human_message, "
                            "not calendar."
                        ),
                        "newsletter": (
                            "Bulk email, marketing email, product update, feature announcement, "
                            "educational mailing, event promotion, or mailing-list content."
                        ),
                        "security": (
                            "Security alert, login warning, vulnerability notice, permission change, "
                            "authentication issue, or account security message."
                        ),
                        "file_share": (
                            "Shared document, design file, spreadsheet, comment notification, "
                            "review request, or collaboration-file notification."
                        ),
                        "system": (
                            "Automated platform, account, service, usage, status, or operational notification."
                        ),
                        "other": (
                            "None of the message types clearly apply."
                        ),
                    },
                ),
                "reply_needed": Noul(
        instructions=(
            "Does the latest meaningful state of this human conversation require the mailbox owner "
            "to send an email reply? Answer yes when another person has asked a direct question, "
            "requested feedback, proposed work, introduced a concrete opportunity, asked for a decision, "
            "or otherwise reasonably expects a written response. "
            "Answer no when the mailbox owner already sent the latest meaningful message and is waiting "
            "for the other person, or when the message is only an automated notification, status update, "
            "newsletter, calendar event, file notification, receipt, or system message."
        )
    ),
    "action_required": Noul(
        instructions=(
            "Does the mailbox owner need to take a concrete action outside of writing an email reply? "
            "Answer yes when something is genuinely waiting for the mailbox owner's decision or action. "
            "Examples include paying or fixing a failed payment, reviewing a security issue, "
            "updating account information, completing a required task, responding to an RSVP, "
            "or approving, denying, granting, changing, or reviewing an access or permission request "
            "for a file, document, workspace, account, project, or other shared resource. "
            "A pending request from another person that cannot proceed until the mailbox owner acts "
            "should count as action required. "
            "Answer no for passive notifications, already-completed permission changes, informational "
            "updates, or messages where no decision or action is currently required. "
            "Optional marketing calls to action do NOT count. Do not count invitations to webinars, "
            "events, discounts, purchases, registrations, applications, 'learn more' links, "
            "or promotional urgency as required actions."
        )
    ),

                "waiting_on_them": Noul(
                    instructions=(
                        f"Is {OWNER} genuinely waiting for another person or organization to respond or complete "
                        f"something after {OWNER} has already replied, asked a question, delivered work, or handed "
                        "off a task? Automated acknowledgements, job application confirmations, shipment tracking, "
                        "status notifications, and passive expectations of a future update do NOT count."
                    )
                ),

                "can_archive": Noul(
                    instructions=(
                        f"Can this thread safely leave the inbox now without causing {OWNER} "
                        "to miss a required reply or action?"
                    )
                ),
                "urgency": Score(
                    instructions=(
                        f"How urgently does {OWNER} need to pay attention to this thread?"
                    ),
                    criteria=["low", "medium", "high"],
                ),
                "revenue_relevance": Score(
                    instructions="How relevant is this thread to current or potential business revenue?",
                    criteria=["low", "medium", "high"],
                ),
            },
        )
    except Exception as e:
        print("\nJEV ERROR:")
        print(state["subject"])
        print(e)
        continue


    print("\nSUBJECT:")
    print(state["subject"])

    print("\nJEV RESULT:")
    print(result)

    # Workflow label IDs are cached once per run.

    answers = result.answers

    relationship = answers["relationship"].choice
    relationship_confidence = answers["relationship"].confidence

    message_type = answers["message_type"].choice
    message_type_confidence = answers["message_type"].confidence

    # MIME evidence is stronger than probabilistic classification for
    # actual calendar invitations and event updates.
    if has_calendar_evidence:
        message_type = "calendar"
        message_type_confidence = max(message_type_confidence, 0.99)

    reply_needed = answers["reply_needed"].noul
    action_required = answers["action_required"].noul
    waiting_on_them = answers["waiting_on_them"].noul
    can_archive = answers["can_archive"].noul


    # label_ids was prepared once before the thread loop.

    add_labels = []

    meaningful_labels = []

    # Relationship/context
    if known_client_matches:
        meaningful_labels.append(label_ids["04 — Clients"])

    elif relationship_confidence >= 0.55:
        if relationship == "client":
            meaningful_labels.append(label_ids["04 — Clients"])
        elif relationship == "lead":
            meaningful_labels.append(label_ids["05 — Leads"])

    message_type_thresholds = {
        "finance": 0.40,
        "calendar": 0.60,
        "newsletter": 0.40,
        "system": 0.40,
        "security": 0.40,
        "file_share": 0.40,
    }

    type_threshold = message_type_thresholds.get(message_type)

    if (
        type_threshold is not None
        and message_type_confidence >= type_threshold
    ):
        if message_type == "finance":
            meaningful_labels.append(label_ids["06 — Finance"])

        elif message_type == "calendar":
            meaningful_labels.append(label_ids["07 — Calendar"])

        elif message_type == "newsletter":
            meaningful_labels.append(label_ids["08 — Read Later"])

        elif message_type in {"system", "security", "file_share"}:
            meaningful_labels.append(label_ids["09 — System"])

    # Actions
    if (
        reply_needed >= 0.50
        and message_type == "human_message"
        and waiting_on_them < 0.70
    ):
        meaningful_labels.append(label_ids["01 — Reply"])

    action_threshold = (
        0.50
        if message_type in {"system", "security", "file_share"}
        else 0.70
    )

    if (
        action_required >= action_threshold
        and message_type != "newsletter"
    ):
        meaningful_labels.append(label_ids["02 — Action Required"])

    if (
        waiting_on_them >= 0.70
        and message_type == "human_message"
        and action_required < 0.70
    ):
        meaningful_labels.append(label_ids["03 — Waiting"])

    # Review = model is materially uncertain.
    # Other = processed successfully but no useful class/action matched.
    uncertain = (
        not known_client_matches
        and relationship_confidence < 0.55
        and message_type_confidence < 0.55
    )


    # Review is an exclusive fallback queue and must be evaluated
    # only after every normal routing rule has had a chance to add a label.
    if uncertain and not meaningful_labels:
        meaningful_labels.append(label_ids["98 — Review"])

    if not meaningful_labels:
        meaningful_labels.append(label_ids["97 — Other"])

    add_labels.extend(meaningful_labels)


    should_archive = (
        (
            message_type == "newsletter"
            and message_type_confidence >= 0.65
        )
        or (
            can_archive >= 0.70
            and reply_needed < 0.50
            and action_required < 0.50
        )
    )

    remove_labels = []

    if should_archive:
        remove_labels.append("INBOX")


    if (add_labels or remove_labels) and not DRY_RUN:
        gmail_execute(
            gmail.users().threads().modify(
                userId="me",
                id=thread["id"],
                body={
                    "addLabelIds": list(set(add_labels)),
                    "removeLabelIds": remove_labels,
                },
            ),
            f"threads.modify:{thread['id']}",
        )

    id_to_name = {
        label_id: label_name
        for label_name, label_id in label_ids.items()
    }

    proposed_label_names = [
        id_to_name.get(label_id, label_id)
        for label_id in list(dict.fromkeys(add_labels))
    ]

    print("\nVALIDATION RESULT:" if DRY_RUN else "\nGMAIL ACTION:")
    print("Relationship:", relationship)
    print("Message type:", message_type)
    print("Known client match:", ", ".join(known_client_matches) if known_client_matches else "None")
    print("Proposed labels:" if DRY_RUN else "Added labels:", proposed_label_names)
    print("Reply needed:", reply_needed)
    print("Action required:", action_required)
    print("Waiting on them:", waiting_on_them)
    print("Archived:" if not DRY_RUN else "Would archive:", should_archive)

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "thread_id": thread["id"],
        "subject": state["subject"],
        "relationship": relationship,
        "relationship_confidence": relationship_confidence,
        "message_type": message_type,
        "message_type_confidence": message_type_confidence,
        "known_client_matches": known_client_matches,
        "calendar_evidence": has_calendar_evidence,
        "reply_needed": reply_needed,
        "action_required": action_required,
        "waiting_on_them": waiting_on_them,
        "can_archive": can_archive,
        "urgency_score": answers["urgency"].score,
        "revenue_relevance_score": answers["revenue_relevance"].score,
        "proposed_labels": proposed_label_names,
        "applied_labels": [] if DRY_RUN else proposed_label_names,
        "archived": should_archive,
    }

    log_path = "validation.jsonl" if DRY_RUN else "decisions.jsonl"

    with open(log_path, "a") as log_file:
        log_file.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
