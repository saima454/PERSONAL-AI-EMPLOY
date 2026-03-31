"""Vault Action Watcher — polls Needs_Action/ for checkbox changes.

When you tick "- [x] Reply to sender" in Obsidian on an email or LinkedIn
message action file, this watcher creates a reply template in
vault/Pending_Approval/ with the relevant IDs and an empty body for you
to fill in.

No LLM involved — purely file-based HITL trigger.

Supported types:
  - email    → creates type: email_reply    template
  - linkedin → creates type: linkedin_reply template

Usage (standalone):
    uv run python backend/watchers/vault_action_watcher.py
    uv run python backend/watchers/vault_action_watcher.py --once

The orchestrator starts this automatically alongside all other watchers.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.utils.frontmatter import (
    create_file_with_frontmatter,
    extract_frontmatter,
    update_frontmatter,
)
from backend.utils.timestamps import format_filename_timestamp, now_iso
from backend.watchers.base_watcher import BaseWatcher

_PROJECT_ROOT = Path(__file__).parents[2]
load_dotenv(dotenv_path=_PROJECT_ROOT / "config" / ".env", override=True)

logger = logging.getLogger(__name__)

REPLY_CHECKBOX = "- [x] Reply to sender"


def _slugify(text: str, max_length: int = 40) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length].rstrip("-")


def _already_has_pending(vault_path: Path, key_field: str, key_value: str) -> bool:
    """Return True if a Pending_Approval file already exists matching key_field=key_value."""
    pending_dir = vault_path / "Pending_Approval"
    if not pending_dir.exists():
        return False
    for f in pending_dir.glob("*.md"):
        try:
            fm, _ = extract_frontmatter(f.read_text(encoding="utf-8"))
            if fm.get(key_field) == key_value:
                return True
        except OSError:
            continue
    return False


# ── Email reply ──────────────────────────────────────────────────────

def _email_pending_frontmatter(fm: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "email_reply",
        "status": "pending_approval",
        "thread_id": fm.get("thread_id", ""),
        "message_id": fm.get("message_id", ""),
        "reply_to": fm.get("from", ""),
        "original_subject": fm.get("subject", ""),
        "original_received": fm.get("received", ""),
        "created_at": now_iso(),
    }


def _email_pending_body(fm: dict[str, Any]) -> str:
    return f"""
## Instructions

1. Write your reply in the **Reply Body** section below.
2. When ready to send, change `status: pending_approval` → `status: approved` (exactly, no typos).
3. Move this file to `vault/Approved/`.
4. The action executor will send it via Gmail and move this file to `vault/Done/`.

---

## Original Email

- **From:** {fm.get("from", "")}
- **Subject:** {fm.get("subject", "")}
- **Received:** {fm.get("received", "")}
- **Thread ID:** `{fm.get("thread_id", "")}`
- **Message ID:** `{fm.get("message_id", "")}`

---

## Reply Body

<!-- Write your reply here. Delete this comment when done. -->

"""


# ── LinkedIn reply ───────────────────────────────────────────────────

def _linkedin_pending_frontmatter(fm: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "linkedin_reply",
        "status": "pending_approval",
        "sender": fm.get("sender", ""),
        "original_preview": fm.get("preview", "")[:300],
        "received": fm.get("received", ""),
        "created_at": now_iso(),
    }


def _linkedin_pending_body(fm: dict[str, Any]) -> str:
    return f"""
## Instructions

1. Write your reply in the **Reply Body** section below.
2. When ready to send, change `status: pending_approval` → `status: approved` (exactly, no typos).
3. Move this file to `vault/Approved/`.
4. The action executor will open LinkedIn and send your reply.

---

## Original Message

- **From:** {fm.get("sender", "")}
- **Received:** {fm.get("received", "")}
- **Preview:** {fm.get("preview", "")[:300]}

---

## Reply Body

<!-- Write your reply here. Delete this comment when done. -->

"""


# ── WhatsApp reply ───────────────────────────────────────────────────

def _whatsapp_pending_frontmatter(fm: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "whatsapp_reply",
        "status": "pending_approval",
        "chat_name": fm.get("chat_name", fm.get("sender", "")),
        "original_preview": fm.get("message_preview", "")[:300],
        "received": fm.get("received", ""),
        "created_at": now_iso(),
    }


def _whatsapp_pending_body(fm: dict[str, Any]) -> str:
    chat = fm.get("chat_name", fm.get("sender", ""))
    return f"""
## Instructions

1. Write your reply in the **Reply Body** section below.
2. When ready to send, change `status: pending_approval` → `status: approved` (exactly, no typos).
3. Move this file to `vault/Approved/`.
4. The action executor will open WhatsApp Web and send your reply.

---

## Original Message

- **From:** {chat}
- **Received:** {fm.get("received", "")}
- **Preview:** {fm.get("message_preview", "")[:300]}

---

## Reply Body

<!-- Write your reply here. Delete this comment when done. -->

"""


# ── Facebook reply ───────────────────────────────────────────────────

def _facebook_pending_frontmatter(fm: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "facebook_reply",
        "status": "pending_approval",
        "sender": fm.get("sender", ""),
        "original_preview": fm.get("preview", "")[:300],
        "received": fm.get("received", ""),
        "created_at": now_iso(),
    }


def _facebook_pending_body(fm: dict[str, Any]) -> str:
    return f"""
## Instructions

1. Write your reply in the **Reply Body** section below.
2. When ready to send, change `status: pending_approval` → `status: approved` (exactly, no typos).
3. Move this file to `vault/Approved/`.
4. The action executor will open Facebook Messenger and send your reply.

---

## Original Message

- **From:** {fm.get("sender", "")}
- **Received:** {fm.get("received", "")}
- **Preview:** {fm.get("preview", "")[:300]}

---

## Reply Body

<!-- Write your reply here. Delete this comment when done. -->

"""


# ── Watcher ──────────────────────────────────────────────────────────

class VaultActionWatcher(BaseWatcher):
    """Polls vault/Needs_Action/ for ticked reply checkboxes.

    Every check_interval seconds it scans all .md files and creates a
    Pending_Approval reply template for any that have '- [x] Reply to sender'.

    Handles:
      - type: email     → email_reply template (uses thread_id / message_id)
      - type: linkedin  → linkedin_reply template (uses sender name)
      - type: whatsapp  → whatsapp_reply template (uses chat_name)
    """

    def __init__(self, vault_path: str, check_interval: int = 5) -> None:
        super().__init__(vault_path, check_interval)

    async def check_for_updates(self) -> list[dict[str, Any]]:
        needs_action = self.vault_path / "Needs_Action"
        if not needs_action.exists():
            return []

        triggered: list[dict[str, Any]] = []

        for md_file in sorted(needs_action.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
            except OSError:
                continue

            if REPLY_CHECKBOX not in content:
                continue

            fm, _ = extract_frontmatter(content)
            file_type = fm.get("type")

            if file_type == "email":
                item = self._check_email(md_file, fm)
            elif file_type == "linkedin" and fm.get("item_type") == "message":
                item = self._check_linkedin(md_file, fm)
            elif file_type == "whatsapp":
                item = self._check_whatsapp(md_file, fm)
            elif file_type == "facebook" and fm.get("item_type") == "message":
                item = self._check_facebook(md_file, fm)
            else:
                continue

            if item:
                triggered.append(item)
                self.logger.info("Reply checkbox detected in: %s", md_file.name)

        return triggered

    def _check_email(self, md_file: Path, fm: dict[str, Any]) -> dict[str, Any] | None:
        if fm.get("status") == "done":
            return None

        thread_id = fm.get("thread_id", "")
        if not thread_id:
            self.logger.warning("No thread_id in %s, skipping", md_file.name)
            return None

        if fm.get("status") == "reply_pending":
            if _already_has_pending(self.vault_path, "thread_id", thread_id):
                self.logger.debug("Pending approval exists for email thread %s", thread_id)
                return None
            self.logger.info("Template missing for %s — re-creating", md_file.name)

        return {"file": md_file, "frontmatter": fm, "kind": "email"}

    def _check_linkedin(self, md_file: Path, fm: dict[str, Any]) -> dict[str, Any] | None:
        if fm.get("status") == "done":
            return None

        sender = fm.get("sender", "")
        if not sender:
            self.logger.warning("No sender in %s, skipping", md_file.name)
            return None

        if fm.get("status") == "reply_pending":
            if _already_has_pending(self.vault_path, "sender", sender):
                self.logger.debug("Pending approval exists for LinkedIn sender %s", sender)
                return None
            self.logger.info("Template missing for %s — re-creating", md_file.name)

        return {"file": md_file, "frontmatter": fm, "kind": "linkedin"}

    def _check_facebook(self, md_file: Path, fm: dict[str, Any]) -> dict[str, Any] | None:
        if fm.get("status") == "done":
            return None

        sender = fm.get("sender", "")
        if not sender:
            self.logger.warning("No sender in %s, skipping", md_file.name)
            return None

        if fm.get("status") == "reply_pending":
            if _already_has_pending(self.vault_path, "sender", sender):
                self.logger.debug("Pending approval exists for Facebook sender %s", sender)
                return None
            self.logger.info("Template missing for %s — re-creating", md_file.name)

        return {"file": md_file, "frontmatter": fm, "kind": "facebook"}

    def _check_whatsapp(self, md_file: Path, fm: dict[str, Any]) -> dict[str, Any] | None:
        if fm.get("status") == "done":
            return None

        chat_name = fm.get("chat_name", fm.get("sender", ""))
        if not chat_name:
            self.logger.warning("No chat_name/sender in %s, skipping", md_file.name)
            return None

        if fm.get("status") == "reply_pending":
            if _already_has_pending(self.vault_path, "chat_name", chat_name):
                self.logger.debug("Pending approval exists for WhatsApp chat %s", chat_name)
                return None
            self.logger.info("Template missing for %s — re-creating", md_file.name)

        return {"file": md_file, "frontmatter": fm, "kind": "whatsapp"}

    async def create_action_file(self, item: dict[str, Any]) -> Path | None:
        md_file: Path = item["file"]
        fm: dict[str, Any] = item["frontmatter"]
        kind: str = item["kind"]

        if kind == "email":
            slug = _slugify(fm.get("subject", "no-subject"))
            prefix = "reply"
            pending_fm = _email_pending_frontmatter(fm)
            pending_body = _email_pending_body(fm)
            log_key = fm.get("from", "")
        elif kind == "linkedin":
            slug = _slugify(fm.get("sender", "unknown"))
            prefix = "linkedin-reply"
            pending_fm = _linkedin_pending_frontmatter(fm)
            pending_body = _linkedin_pending_body(fm)
            log_key = fm.get("sender", "")
        elif kind == "whatsapp":
            slug = _slugify(fm.get("chat_name", fm.get("sender", "unknown")))
            prefix = "whatsapp-reply"
            pending_fm = _whatsapp_pending_frontmatter(fm)
            pending_body = _whatsapp_pending_body(fm)
            log_key = fm.get("chat_name", fm.get("sender", ""))
        else:  # facebook
            slug = _slugify(fm.get("sender", "unknown"))
            prefix = "facebook-reply"
            pending_fm = _facebook_pending_frontmatter(fm)
            pending_body = _facebook_pending_body(fm)
            log_key = fm.get("sender", "")

        timestamp = format_filename_timestamp()
        filename = f"{prefix}-{slug}-{timestamp}.md"

        pending_dir = self.vault_path / "Pending_Approval"
        pending_dir.mkdir(parents=True, exist_ok=True)
        pending_path = pending_dir / filename

        create_file_with_frontmatter(pending_path, pending_fm, pending_body)

        try:
            update_frontmatter(md_file, {"status": "reply_pending"})
        except OSError:
            self.logger.warning("Could not update status on %s", md_file.name)

        self.logger.info("Created pending approval: %s (%s)", filename, log_key)
        return pending_path


# ── Standalone CLI ───────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vault Action Watcher — detects reply checkboxes in Needs_Action files"
    )
    parser.add_argument("--once", action="store_true", help="Scan once and exit")
    args = parser.parse_args()

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    vault_path = os.getenv("VAULT_PATH", "./vault")
    watcher = VaultActionWatcher(vault_path=vault_path, check_interval=5)

    async def _run() -> None:
        if args.once:
            items = await watcher.check_for_updates()
            for item in items:
                path = await watcher.create_action_file(item)
                if path:
                    print(f"[VAULT WATCHER] Created: {path}")
            print(f"[VAULT WATCHER] Scanned. Found {len(items)} item(s).")
        else:
            logger.info("Watching vault/Needs_Action/ every 5s (Ctrl+C to stop)...")
            await watcher.run()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
