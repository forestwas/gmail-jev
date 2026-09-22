import os
import json
import socket
import time
from datetime import datetime

from dotenv import load_dotenv

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

from routing import (
    decide_label_names,
    find_known_client_matches,
    should_archive_thread,
)
from gmail_utils import decode_body, get_header, has_calendar_part
from workflow import DEFAULT_GMAIL_QUERY, SCOPES, WORKFLOW_LABELS


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


def gmail_execute(request, operation, retry_attempts):
    for attempt in range(retry_attempts):
        try:
            return request.execute()

        except HttpError as exc:
            if (
                not is_retryable_http_error(exc)
                or attempt == retry_attempts - 1
            ):
                raise

            error_name = (
                f"HTTP {getattr(exc.resp, 'status', '?')}"
            )

        except (TimeoutError, socket.timeout, OSError) as exc:
            if attempt == retry_attempts - 1:
                raise

            error_name = type(exc).__name__

        delay = min(2 ** (attempt + 1), 30)

        print(
            f"Gmail {operation} failed with {error_name}; "
            f"retrying in {delay}s "
            f"({attempt + 1}/{retry_attempts})..."
        )

        time.sleep(delay)

    raise RuntimeError(
        f"Gmail operation failed unexpectedly: {operation}"
    )


def load_known_clients(path):
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARNING: Could not load {path}: {exc}")
        return []

    return data.get("clients", [])


def build_jev_questions(owner):
    return {
        "relationship": Choice(
            instructions=(
                f"What is {owner}'s relationship to this thread? "
                "Classify the business or personal relationship, not the message format."
            ),
            criteria={
                "client": (
                    f"An existing paid client or active client project where {owner} is providing "
                    "professional services. This can include project-tool notifications tied to that client. "
                    f"Do NOT classify companies {owner} buys from, merchants, SaaS providers, vendors, "
                    f"subscription services, invoices sent to {owner}, purchases, receipts, orders, "
                    f"shipments, or other businesses where {owner} is the customer as clients."
                ),
                "lead": (
                    f"A real potential buyer of {owner}'s professional services, a concrete project inquiry, "
                    f"business introduction, or partnership opportunity directed specifically to {owner}. "
                    "Do NOT classify newsletters, webinars, conferences, promotions, generic sales outreach, "
                    f"job alerts, marketing invitations, or companies trying to sell something to {owner} as leads."
                ),
                "personal": (
                    f"A direct personal human conversation unrelated to {owner}'s professional work."
                ),
                "other": (
                    "No active client, genuine sales lead, or personal relationship applies. "
                    f"This includes vendors, merchants, services {owner} subscribes to, ecommerce purchases, "
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
                f"Is {owner} genuinely waiting for another person or organization to respond or complete "
                f"something after {owner} has already replied, asked a question, delivered work, or handed "
                "off a task? Automated acknowledgements, job application confirmations, shipment tracking, "
                "status notifications, and passive expectations of a future update do NOT count."
            )
        ),
        "can_archive": Noul(
            instructions=(
                f"Can this thread safely leave the inbox now without causing {owner} "
                "to miss a required reply or action?"
            )
        ),
        "urgency": Score(
            instructions=(
                f"How urgently does {owner} need to pay attention to this thread?"
            ),
            criteria=["low", "medium", "high"],
        ),
        "revenue_relevance": Score(
            instructions="How relevant is this thread to current or potential business revenue?",
            criteria=["low", "medium", "high"],
        ),
    }


def prepare_workflow_labels(service, dry_run, retry_attempts):
    existing = gmail_execute(
        service.users().labels().list(
            userId="me"
        ),
        "labels.list",
        retry_attempts,
    ).get("labels", [])

    label_ids = {
        label["name"]: label["id"]
        for label in existing
    }

    for label_name in WORKFLOW_LABELS:
        if label_name in label_ids:
            continue

        if dry_run:
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


def process_thread(
    *,
    gmail,
    thread,
    jev,
    questions,
    known_clients,
    label_ids,
    dry_run,
    retry_attempts,
):
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
        thread_text = (
            thread_text[:4000]
            + "\n\n--- TRUNCATED ---\n\n"
            + thread_text[-16000:]
        )

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
        known_clients,
        state["subject"],
        thread_text,
        participant_headers,
    )

    try:
        result = jev.system_one(
            state=state,
            questions=questions,
        )
    except Exception as e:
        print("\nJEV ERROR:")
        print(state["subject"])
        print(e)
        return

    print("\nSUBJECT:")
    print(state["subject"])

    print("\nJEV RESULT:")
    print(result)

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

    proposed_label_names = decide_label_names(
        known_client_matches=known_client_matches,
        relationship=relationship,
        relationship_confidence=relationship_confidence,
        message_type=message_type,
        message_type_confidence=message_type_confidence,
        reply_needed=reply_needed,
        action_required=action_required,
        waiting_on_them=waiting_on_them,
    )

    add_labels = [label_ids[name] for name in proposed_label_names]

    should_archive = should_archive_thread(
        message_type=message_type,
        message_type_confidence=message_type_confidence,
        can_archive=can_archive,
        reply_needed=reply_needed,
        action_required=action_required,
    )

    remove_labels = ["INBOX"] if should_archive else []

    if (add_labels or remove_labels) and not dry_run:
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
            retry_attempts,
        )

    print("\nVALIDATION RESULT:" if dry_run else "\nGMAIL ACTION:")
    print("Relationship:", relationship)
    print("Message type:", message_type)
    print(
        "Known client match:",
        ", ".join(known_client_matches) if known_client_matches else "None",
    )
    print(
        "Proposed labels:" if dry_run else "Added labels:",
        proposed_label_names,
    )
    print("Reply needed:", reply_needed)
    print("Action required:", action_required)
    print("Waiting on them:", waiting_on_them)
    print("Archived:" if not dry_run else "Would archive:", should_archive)

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
        "applied_labels": [] if dry_run else proposed_label_names,
        "archived": should_archive,
    }

    log_path = "validation.jsonl" if dry_run else "decisions.jsonl"

    with open(log_path, "a") as log_file:
        log_file.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def main():
    load_dotenv()

    dry_run = os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}
    max_results = int(os.getenv("MAX_RESULTS", "100"))
    owner = os.getenv("MAILBOX_OWNER_NAME", "the mailbox owner")
    known_clients_file = os.getenv(
        "KNOWN_CLIENTS_FILE",
        "clients.local.json",
    )
    retry_attempts = int(os.getenv("GMAIL_RETRY_ATTEMPTS", "6"))
    gmail_query = os.getenv("GMAIL_QUERY", DEFAULT_GMAIL_QUERY)

    known_clients = load_known_clients(known_clients_file)

    gmail = get_gmail_service()
    jev = TypeSafeClient(api_key=os.environ["TYPESAFE_API_KEY"])
    questions = build_jev_questions(owner)

    results = gmail_execute(
        gmail.users().threads().list(
            userId="me",
            q=gmail_query,
            maxResults=max_results,
        ),
        "threads.list",
        retry_attempts,
    )

    threads = results.get("threads", [])

    if not threads:
        print("Inbox is empty.")
        return

    label_ids = prepare_workflow_labels(
        gmail,
        dry_run,
        retry_attempts,
    )

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
            retry_attempts,
        )

        process_thread(
            gmail=gmail,
            thread=thread,
            jev=jev,
            questions=questions,
            known_clients=known_clients,
            label_ids=label_ids,
            dry_run=dry_run,
            retry_attempts=retry_attempts,
        )


if __name__ == "__main__":
    main()
