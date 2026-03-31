"""Gmail debug script - diagnoses what the watcher sees vs. what it processes.

Usage:
    uv run python scripts/test_gmail_debug.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

CREDENTIALS_PATH = Path(os.getenv("GMAIL_CREDENTIALS_PATH", "config/credentials.json"))
TOKEN_PATH = Path(os.getenv("GMAIL_TOKEN_PATH", "config/token.json"))
PROCESSED_IDS_PATH = Path("vault/Logs/processed_emails.json")
GMAIL_CONFIG_PATH = Path("config/gmail_config.json")

SIMPLE_QUERY = "is:unread"
WATCHER_QUERY = "is:unread (is:important OR urgent OR invoice OR payment OR asap OR help OR deadline)"


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def authenticate() -> object:
    """Authenticate and return Gmail API service."""
    print(f"\n[AUTH] Loading token from: {TOKEN_PATH}")
    if not TOKEN_PATH.exists():
        print(f"  ERROR: Token file not found at {TOKEN_PATH}")
        print("  Run: uv run python skills/gmail-watcher/scripts/setup_gmail_oauth.py")
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds.expired and creds.refresh_token:
        print("  Token expired — refreshing...")
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        print("  Token refreshed and saved.")

    if not creds.valid:
        print("  ERROR: Credentials are not valid and could not be refreshed.")
        sys.exit(1)

    print("  Auth OK")
    return build("gmail", "v1", credentials=creds)


def fetch_subjects(service, query: str, max_results: int) -> list[dict]:
    """Return list of {id, subject, from, is_processed} for query results."""
    results = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    messages = results.get("messages", [])
    items = []
    for msg_ref in messages:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_ref["id"], format="metadata",
                 metadataHeaders=["Subject", "From"])
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        items.append({
            "id": msg_ref["id"],
            "subject": _get_header(headers, "Subject") or "(no subject)",
            "from": _get_header(headers, "From") or "(unknown)",
        })
    return items


def load_processed_ids() -> dict[str, str]:
    """Return {msg_id: processed_at} from vault/Logs/processed_emails.json."""
    if not PROCESSED_IDS_PATH.exists():
        return {}
    try:
        data = json.loads(PROCESSED_IDS_PATH.read_text(encoding="utf-8"))
        return data.get("processed_ids", {})
    except (json.JSONDecodeError, KeyError):
        return {}


def load_watcher_query() -> str:
    """Return the query string from gmail_config.json, or the default."""
    if GMAIL_CONFIG_PATH.exists():
        try:
            cfg = json.loads(GMAIL_CONFIG_PATH.read_text(encoding="utf-8"))
            return cfg.get("query", WATCHER_QUERY)
        except (json.JSONDecodeError, KeyError):
            pass
    return WATCHER_QUERY


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print("=" * 60)


def main() -> None:
    section("Gmail Debug Diagnostic")

    # ── Step 1: Authenticate ────────────────────────────────────────
    service = authenticate()

    processed_ids = load_processed_ids()
    watcher_query = load_watcher_query()

    # ── Step 2: Simple unread query ─────────────────────────────────
    section("QUERY 1 — Simple: is:unread  (maxResults=5)")
    print(f"  Query: {SIMPLE_QUERY}")
    simple_emails = fetch_subjects(service, SIMPLE_QUERY, max_results=5)
    print(f"  Count: {len(simple_emails)}")
    for i, e in enumerate(simple_emails, 1):
        blocked = " [ALREADY PROCESSED]" if e["id"] in processed_ids else ""
        print(f"  {i}. [{e['id']}]{blocked}")
        print(f"     Subject: {e['subject']}")
        print(f"     From:    {e['from']}")

    # ── Step 3: Watcher's exact query ───────────────────────────────
    section(f"QUERY 2 — Watcher exact query  (maxResults=10)")
    print(f"  Query: {watcher_query}")
    watcher_emails = fetch_subjects(service, watcher_query, max_results=10)
    print(f"  Count: {len(watcher_emails)}")

    new_count = 0
    blocked_count = 0
    for i, e in enumerate(watcher_emails, 1):
        already = e["id"] in processed_ids
        tag = " [ALREADY PROCESSED — SKIPPED BY WATCHER]" if already else " [NEW — WATCHER WOULD ACT]"
        if already:
            blocked_count += 1
        else:
            new_count += 1
        print(f"  {i}. [{e['id']}]{tag}")
        print(f"     Subject: {e['subject']}")
        print(f"     From:    {e['from']}")

    # ── Step 4: processed_emails.json analysis ──────────────────────
    section("processed_emails.json Analysis")
    if not processed_ids:
        print("  File is empty or missing — no IDs being blocked.")
    else:
        print(f"  Total tracked IDs: {len(processed_ids)}")
        print(f"  Blocking watcher results: {blocked_count} of {len(watcher_emails)}")
        print("\n  All tracked IDs (oldest first):")
        for msg_id, ts in sorted(processed_ids.items(), key=lambda x: x[1]):
            print(f"    {msg_id}  processed at {ts}")

    # ── Step 5: Summary ─────────────────────────────────────────────
    section("SUMMARY")
    print(f"  Unread emails (any):               {len(simple_emails)} (showing first 5)")
    print(f"  Watcher query matches:             {len(watcher_emails)}")
    print(f"    - Already processed (skipped):   {blocked_count}")
    print(f"    - New (watcher would act on):    {new_count}")
    print(f"  Tracked processed IDs on disk:     {len(processed_ids)}")

    if len(watcher_emails) == 0:
        print("\n  DIAGNOSIS: No emails match the watcher query at all.")
        print("  ->The Gmail filter may be too narrow, or inbox is empty/read.")
    elif new_count == 0 and len(watcher_emails) > 0:
        print("\n  DIAGNOSIS: All matching emails are already in processed_emails.json.")
        print("  ->The watcher has seen these before and will skip them.")
        print("  ->To reprocess, clear vault/Logs/processed_emails.json")
    elif new_count > 0:
        print(f"\n  DIAGNOSIS: {new_count} email(s) are NEW and the watcher SHOULD create action files.")
        print("  ->If the watcher isn't acting, check dry_run / dev_mode settings.")
    print()


if __name__ == "__main__":
    main()
