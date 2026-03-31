"""Action executor — polls vault/Approved/ and dispatches approved actions.

Reads frontmatter from approval files to determine the action type, then
routes to the appropriate handler (email_send, email_reply, linkedin_post).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.utils.frontmatter import extract_frontmatter, update_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso
from backend.utils.uuid_utils import correlation_id

if TYPE_CHECKING:
    from backend.orchestrator.orchestrator import OrchestratorConfig

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Polls vault/Approved/ and dispatches approved actions by type."""

    HANDLERS: dict[str, str] = {
        "email_send": "_handle_email_send",
        "email_reply": "_handle_email_reply",
        "linkedin_post": "_handle_linkedin_post",
        "linkedin_reply": "_handle_linkedin_reply",
        "whatsapp_reply": "_handle_whatsapp_reply",
        "facebook_post": "_handle_facebook_post",
        "facebook_reply": "_handle_facebook_reply",
        "instagram_post": "_handle_instagram_post",
        "twitter_post": "_handle_twitter_post",
        "odoo_invoice": "_handle_odoo_invoice",
        "odoo_payment": "_handle_odoo_payment",
    }

    def __init__(self, config: OrchestratorConfig) -> None:
        self.config = config
        self.vault_path = Path(config.vault_path)
        self.approved_dir = self.vault_path / "Approved"
        self.done_dir = self.vault_path / "Done"
        self.log_dir = self.vault_path / "Logs" / "actions"
        self._gmail_client: Any = None
        self._rate_limiter: Any = None
        self._odoo_client: Any = None

    async def run(self) -> None:
        """Polling loop — scan Approved folder every check_interval seconds."""
        logger.info("Action executor watching %s", self.approved_dir)
        while True:
            try:
                await self._process_cycle()
            except asyncio.CancelledError:
                logger.info("Action executor stopped")
                return
            except Exception:
                logger.exception("Error in action executor cycle")
            await asyncio.sleep(self.config.check_interval)

    async def _process_cycle(self) -> None:
        """Single scan + process cycle."""
        files = self._scan_approved()
        for file_path, frontmatter in files:
            await self.process_file(file_path, frontmatter)

    def _scan_approved(self) -> list[tuple[Path, dict[str, Any]]]:
        """List .md files in vault/Approved/ with parsed frontmatter."""
        if not self.approved_dir.exists():
            return []

        results: list[tuple[Path, dict[str, Any]]] = []
        for md_file in sorted(self.approved_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
                fm, _ = extract_frontmatter(content)
                if fm and fm.get("status") == "approved":
                    results.append((md_file, fm))
            except (OSError, UnicodeDecodeError):
                logger.warning("Failed to read approval file: %s", md_file)
        return results

    async def process_file(self, file_path: Path, fm: dict[str, Any]) -> bool:
        """Process a single approval file. Returns True on success."""
        action_type = fm.get("type", "")
        cid = correlation_id()

        logger.info("Processing: %s (type=%s)", file_path.name, action_type)

        # DEV_MODE — log and move to Done
        if self.config.dev_mode:
            return await self._handle_dev_mode(file_path, fm, cid)

        # Look up handler
        handler_name = self.HANDLERS.get(action_type)
        if not handler_name:
            logger.warning("Unknown action type '%s' in %s — skipping", action_type, file_path.name)
            self._log_event(
                cid, "action_skipped", file_path.name, "failure", f"Unknown type: {action_type}"
            )
            return False

        handler = getattr(self, handler_name)

        try:
            await handler(file_path, fm, cid)
            # Skip _move_to_done() if the handler (e.g. LinkedInPoster) already moved the file
            if file_path.exists():
                self._move_to_done(file_path)
            else:
                logger.debug(
                    "File already moved by handler — skipping executor move: %s",
                    file_path.name,
                )
            self._log_event(
                cid, "action_executed", file_path.name, "success", f"type={action_type}"
            )
            logger.info("Completed: %s → vault/Done/", file_path.name)
            return True
        except Exception as exc:
            logger.exception("Failed to execute %s: %s", file_path.name, exc)
            self._log_event(cid, "action_failed", file_path.name, "failure", str(exc)[:200])
            return False

    # ── Handlers ─────────────────────────────────────────────────

    async def _handle_email_send(self, file_path: Path, fm: dict[str, Any], _cid: str) -> None:
        """Send email using GmailClient + RateLimiter."""
        client = self._get_gmail_client()
        rate_limiter = self._get_rate_limiter()

        # Rate limit check
        allowed, wait = rate_limiter.check()
        if not allowed:
            raise RuntimeError(f"Rate limit exceeded, wait {wait}s")

        to = fm.get("to", "")
        subject = fm.get("subject", "")
        # Read body from file content (after frontmatter)
        content = file_path.read_text(encoding="utf-8")
        _, body_text = extract_frontmatter(content)
        body = self._extract_email_body(body_text)

        if not to or not subject:
            raise ValueError(f"Missing required fields: to={to!r}, subject={subject!r}")

        # Send via asyncio.to_thread (GmailClient is synchronous)
        await asyncio.to_thread(client.authenticate)
        result = await asyncio.to_thread(client.send_message, to, subject, body)
        rate_limiter.record_send()

        logger.info("Email sent to %s (message_id=%s)", to, result.get("id", "?"))

    async def _handle_email_reply(self, file_path: Path, fm: dict[str, Any], _cid: str) -> None:
        """Reply to an email thread using GmailClient."""
        client = self._get_gmail_client()
        rate_limiter = self._get_rate_limiter()

        allowed, wait = rate_limiter.check()
        if not allowed:
            raise RuntimeError(f"Rate limit exceeded, wait {wait}s")

        thread_id = fm.get("thread_id", "")
        message_id = fm.get("message_id", "")
        content = file_path.read_text(encoding="utf-8")
        _, body_text = extract_frontmatter(content)
        body = self._extract_email_body(body_text)

        if not thread_id:
            raise ValueError(f"Missing thread_id in {file_path.name}")

        await asyncio.to_thread(client.authenticate)
        result = await asyncio.to_thread(client.reply_to_thread, thread_id, message_id, body)
        rate_limiter.record_send()

        logger.info("Reply sent (thread=%s, message_id=%s)", thread_id, result.get("id", "?"))

    async def _handle_linkedin_post(self, file_path: Path, _fm: dict[str, Any], _cid: str) -> None:
        """Publish an approved LinkedIn post via LinkedInPoster.

        LinkedInPoster.process_approved_posts() handles reading the file,
        posting to LinkedIn, and moving the file to vault/Done/ itself.
        Therefore this handler must NOT call self._move_to_done() afterward
        (the file lifecycle collision is handled in process_file()).
        """
        from backend.actions.linkedin_poster import LinkedInPoster

        poster = LinkedInPoster(
            vault_path=str(self.vault_path),
            session_path=os.getenv("LINKEDIN_SESSION_PATH", "config/linkedin_session"),
            headless=os.getenv("LINKEDIN_HEADLESS", "true").lower() == "true",
            dry_run=self.config.dry_run,
            dev_mode=self.config.dev_mode,
        )
        try:
            count = await poster.process_approved_posts()
        finally:
            await poster._close_browser()

        if count == 0:
            raise RuntimeError(
                f"LinkedInPoster processed 0 posts for {file_path.name} — "
                "check session state or post content"
            )

    async def _handle_linkedin_reply(self, file_path: Path, _fm: dict[str, Any], _cid: str) -> None:
        """Send an approved LinkedIn message reply via LinkedInReplier.

        LinkedInReplier.process_reply_file() handles reading the file,
        sending the reply on LinkedIn, and moving the file to vault/Done/ itself.
        Therefore this handler must NOT call self._move_to_done() afterward
        (the file lifecycle collision is handled in process_file()).
        """
        from backend.actions.linkedin_replier import LinkedInReplier

        replier = LinkedInReplier(
            vault_path=str(self.vault_path),
            session_path=os.getenv("LINKEDIN_SESSION_PATH", "config/linkedin_session"),
            headless=os.getenv("LINKEDIN_HEADLESS", "true").lower() == "true",
            dry_run=self.config.dry_run,
            dev_mode=self.config.dev_mode,
        )
        try:
            success = await replier.process_reply_file(file_path)
        finally:
            await replier._close_browser()

        if not success:
            raise RuntimeError(
                f"LinkedInReplier failed to send reply for {file_path.name} — "
                "check session state or reply content"
            )

    async def _handle_whatsapp_reply(self, file_path: Path, _fm: dict[str, Any], _cid: str) -> None:
        """Send an approved WhatsApp reply via WhatsAppReplier.

        WhatsAppReplier.process_reply_file() handles reading the file,
        sending the reply on WhatsApp Web, and moving the file to vault/Done/ itself.
        Therefore this handler must NOT call self._move_to_done() afterward.
        """
        from backend.actions.whatsapp_replier import WhatsAppReplier

        replier = WhatsAppReplier(
            vault_path=str(self.vault_path),
            session_path=os.getenv("WHATSAPP_SESSION_PATH", "config/whatsapp_session"),
            headless=os.getenv("WHATSAPP_HEADLESS", "true").lower() == "true",
            dry_run=self.config.dry_run,
            dev_mode=self.config.dev_mode,
        )
        try:
            success = await replier.process_reply_file(file_path)
        finally:
            await replier._close_browser()

        if not success:
            raise RuntimeError(
                f"WhatsAppReplier failed to send reply for {file_path.name} — "
                "check session state or reply content"
            )

    async def _handle_facebook_post(self, file_path: Path, _fm: dict[str, Any], _cid: str) -> None:
        """Publish an approved Facebook post via FacebookPoster.

        FacebookPoster.process_approved_posts() handles reading the file,
        posting to Facebook, and moving the file to vault/Done/ itself.
        Therefore this handler must NOT call self._move_to_done() afterward.
        """
        from backend.actions.facebook_poster import FacebookPoster

        poster = FacebookPoster(
            vault_path=str(self.vault_path),
            session_path=os.getenv("FACEBOOK_SESSION_PATH", "config/meta_session"),
            headless=os.getenv("FACEBOOK_HEADLESS", "true").lower() == "true",
            dry_run=self.config.dry_run,
            dev_mode=self.config.dev_mode,
        )
        try:
            count = await poster.process_approved_posts()
        finally:
            await poster._close_browser()

        if count == 0:
            raise RuntimeError(
                f"FacebookPoster processed 0 posts for {file_path.name} — "
                "check session state or post content"
            )

    async def _handle_facebook_reply(self, file_path: Path, fm: dict[str, Any], cid: str) -> None:
        """Send an approved Facebook Messenger reply via FacebookReplier."""
        from backend.actions.facebook_replier import FacebookReplier

        replier = FacebookReplier(
            vault_path=str(self.vault_path),
            session_path=os.getenv("FACEBOOK_SESSION_PATH", "config/meta_session"),
            headless=os.getenv("FACEBOOK_HEADLESS", "false").lower() == "true",
            dry_run=self.config.dry_run,
            dev_mode=self.config.dev_mode,
        )
        try:
            await replier.send_reply(file_path, fm)
        finally:
            await replier._close_browser()

        self._move_to_done(file_path, cid)

    async def _handle_instagram_post(self, file_path: Path, _fm: dict[str, Any], _cid: str) -> None:
        """Publish an approved Instagram post via InstagramPoster.

        InstagramPoster.process_approved_posts() handles reading the file,
        posting to Instagram, and moving the file to vault/Done/ itself.
        Therefore this handler must NOT call self._move_to_done() afterward.
        """
        from backend.actions.instagram_poster import InstagramPoster

        poster = InstagramPoster(
            vault_path=str(self.vault_path),
            session_path=os.getenv("INSTAGRAM_SESSION_PATH", "config/meta_session"),
            headless=os.getenv("INSTAGRAM_HEADLESS", "true").lower() == "true",
            dry_run=self.config.dry_run,
            dev_mode=self.config.dev_mode,
        )
        try:
            count = await poster.process_approved_posts()
        finally:
            await poster._close_browser()

        if count == 0:
            raise RuntimeError(
                f"InstagramPoster processed 0 posts for {file_path.name} — "
                "check session state or post content"
            )

    async def _handle_twitter_post(self, file_path: Path, _fm: dict[str, Any], _cid: str) -> None:
        """Publish an approved Twitter post via TwitterPoster.

        TwitterPoster.process_approved_posts() handles reading the file,
        posting to Twitter/X, and moving the file to vault/Done/ itself.
        Therefore this handler must NOT call self._move_to_done() afterward.
        """
        from backend.actions.twitter_poster import TwitterPoster

        poster = TwitterPoster(
            vault_path=str(self.vault_path),
            session_path=os.getenv("TWITTER_SESSION_PATH", "config/twitter_session"),
            headless=os.getenv("TWITTER_HEADLESS", "false").lower() == "true",
            dry_run=self.config.dry_run,
            dev_mode=self.config.dev_mode,
        )
        try:
            count = await poster.process_approved_posts()
        finally:
            await poster._close_browser()

        if count == 0:
            raise RuntimeError(
                f"TwitterPoster processed 0 posts for {file_path.name} — "
                "check session state or post content"
            )

    async def _handle_odoo_invoice(self, file_path: Path, fm: dict[str, Any], cid: str) -> None:
        """Create a customer invoice in Odoo from an approved invoice file.

        Reads customer_id, invoice_date, and lines from frontmatter,
        creates the invoice via OdooClient, and updates frontmatter
        with the resulting Odoo invoice ID and reference.
        Auto-creates the customer in Odoo if the customer_id doesn't exist.
        Logs to both vault/Logs/actions/ and vault/Logs/odoo/.
        """
        client = self._get_odoo_client()

        customer_id = fm.get("customer_id")
        customer_name = fm.get("customer_name", "Unknown")
        invoice_date = fm.get("invoice_date", "")
        lines = fm.get("lines", [])

        if not customer_name or customer_name == "Unknown":
            raise ValueError(f"Missing customer_name in {file_path.name}")
        if not lines:
            raise ValueError(f"Missing line items in {file_path.name}")

        await asyncio.to_thread(client.authenticate)

        # Auto-create customer if customer_id is missing or doesn't exist
        actual_customer_id = await self._ensure_odoo_customer(
            client, customer_id, customer_name
        )
        if actual_customer_id != customer_id:
            logger.info(
                "Customer ID resolved: %s → %d for '%s'",
                customer_id, actual_customer_id, customer_name,
            )
            try:
                update_frontmatter(file_path, {"customer_id": actual_customer_id})
            except Exception:
                pass
            customer_id = actual_customer_id

        invoice_id, invoice_ref = await asyncio.to_thread(
            client.create_invoice, int(customer_id), str(invoice_date), lines
        )

        # Update frontmatter with Odoo result data
        try:
            update_frontmatter(file_path, {
                "odoo_invoice_id": invoice_id,
                "odoo_invoice_ref": invoice_ref,
            })
        except Exception:
            logger.warning("Could not update frontmatter with Odoo data on %s", file_path.name)

        # Log to vault/Logs/odoo/
        total = sum(
            float(l.get("quantity", 0)) * float(l.get("price_unit", 0)) for l in lines
        )
        self._log_odoo_event(cid, "create_invoice", {
            "odoo_invoice_id": invoice_id,
            "odoo_invoice_ref": invoice_ref,
            "customer_id": int(customer_id),
            "customer_name": customer_name,
            "invoice_date": str(invoice_date),
            "line_count": len(lines),
            "estimated_total": total,
            "source_file": file_path.name,
            "dev_mode": self.config.dev_mode,
        })

        logger.info(
            "Odoo invoice created: id=%d ref=%s (file=%s)",
            invoice_id, invoice_ref, file_path.name,
        )

    async def _handle_odoo_payment(self, file_path: Path, fm: dict[str, Any], cid: str) -> None:
        """Register a payment against an Odoo invoice from an approved payment file.

        Reads invoice_id, amount, payment_date, journal_id, and optional memo
        from frontmatter, creates the payment via OdooClient, and updates
        frontmatter with the resulting Odoo payment ID.
        Logs to both vault/Logs/actions/ and vault/Logs/odoo/.
        """
        client = self._get_odoo_client()

        invoice_id = fm.get("invoice_id") or fm.get("odoo_invoice_id")
        amount = fm.get("amount", 0)
        payment_date = fm.get("payment_date", "")
        journal_id = fm.get("journal_id", 0)
        memo = fm.get("memo", "")

        if not invoice_id:
            raise ValueError(f"Missing invoice_id in {file_path.name}")
        if not amount or float(amount) <= 0:
            raise ValueError(f"Invalid payment amount in {file_path.name}")
        if not journal_id:
            raise ValueError(f"Missing journal_id in {file_path.name}")

        await asyncio.to_thread(client.authenticate)
        payment_id = await asyncio.to_thread(
            client.create_payment,
            int(invoice_id), float(amount), str(payment_date), int(journal_id), str(memo),
        )

        try:
            update_frontmatter(file_path, {"odoo_payment_id": payment_id})
        except Exception:
            logger.warning("Could not update frontmatter with payment data on %s", file_path.name)

        # Log to vault/Logs/odoo/
        self._log_odoo_event(cid, "create_payment", {
            "odoo_payment_id": payment_id,
            "invoice_id": int(invoice_id),
            "amount": float(amount),
            "payment_date": str(payment_date),
            "journal_id": int(journal_id),
            "memo": memo,
            "source_file": file_path.name,
            "dev_mode": self.config.dev_mode,
        })

        logger.info(
            "Odoo payment created: id=%d for invoice=%s (file=%s)",
            payment_id, invoice_id, file_path.name,
        )

    # ── DEV_MODE Handler ─────────────────────────────────────────

    async def _handle_dev_mode(self, file_path: Path, fm: dict[str, Any], cid: str) -> bool:
        """In DEV_MODE: log the action and move to Done with a note."""
        action_type = fm.get("type", "unknown")
        logger.info("[DEV_MODE] Would execute %s from %s", action_type, file_path.name)

        self._log_event(
            cid, "action_dev_mode", file_path.name, "success", f"[DEV_MODE] type={action_type}"
        )

        # Update frontmatter and move to Done
        try:
            update_frontmatter(
                file_path,
                {
                    "status": "done",
                    "completed_at": now_iso(),
                    "dev_mode_note": "[DEV_MODE] Action logged but not executed",
                },
            )
        except Exception:
            logger.warning("Could not update frontmatter before moving %s", file_path.name)

        self._move_to_done_raw(file_path)
        return True

    # ── Helpers ───────────────────────────────────────────────────

    async def _ensure_odoo_customer(
        self, client: Any, customer_id: Any, customer_name: str
    ) -> int:
        """Ensure the customer exists in Odoo, creating if needed.

        Args:
            client: Authenticated OdooClient instance.
            customer_id: Expected customer ID from frontmatter (may be None).
            customer_name: Customer name to create if not found.

        Returns:
            The actual Odoo partner ID to use for the invoice.
        """
        # First try: use create_customer which handles duplicate detection
        new_id, created = await asyncio.to_thread(
            client.create_customer, customer_name
        )
        if created:
            logger.info("Auto-created customer '%s' in Odoo (id=%d)", customer_name, new_id)
        else:
            logger.info("Customer '%s' already exists in Odoo (id=%d)", customer_name, new_id)
        return new_id

    def _get_gmail_client(self) -> Any:
        """Lazily create the GmailClient."""
        if self._gmail_client is None:
            from backend.mcp_servers.gmail_client import GmailClient

            self._gmail_client = GmailClient(
                credentials_path=os.getenv("GMAIL_CREDENTIALS_PATH", "config/credentials.json"),
                token_path=os.getenv("GMAIL_TOKEN_PATH", "config/token.json"),
            )
        return self._gmail_client

    def _get_rate_limiter(self) -> Any:
        """Lazily create the RateLimiter."""
        if self._rate_limiter is None:
            from backend.mcp_servers.rate_limiter import RateLimiter

            self._rate_limiter = RateLimiter()
        return self._rate_limiter

    def _get_odoo_client(self) -> Any:
        """Lazily create the OdooClient."""
        if self._odoo_client is None:
            from backend.mcp_servers.odoo.odoo_client import OdooClient

            self._odoo_client = OdooClient(
                url=os.getenv("ODOO_URL", "http://localhost:8069"),
                db=os.getenv("ODOO_DATABASE", "ai_employee"),
                username=os.getenv("ODOO_USERNAME", ""),
                api_key=os.getenv("ODOO_API_KEY", ""),
                dev_mode=self.config.dev_mode,
            )
        return self._odoo_client

    def _move_to_done(self, file_path: Path) -> None:
        """Update frontmatter with completion info and move to vault/Done/."""
        try:
            update_frontmatter(file_path, {"status": "done", "completed_at": now_iso()})
        except Exception:
            logger.warning("Could not update frontmatter on %s", file_path.name)
        self._move_to_done_raw(file_path)

    def _move_to_done_raw(self, file_path: Path) -> None:
        """Move file from current location to vault/Done/."""
        import shutil

        self.done_dir.mkdir(parents=True, exist_ok=True)
        dest = self.done_dir / file_path.name
        shutil.move(str(file_path), str(dest))

    @staticmethod
    def _extract_email_body(body_text: str) -> str:
        """Extract email body from markdown content.

        Checks for these section headings in order:
          1. '## Reply Body'   — reply templates created by VaultActionWatcher
          2. '## Email Content' — send templates

        Strips HTML comments (<!-- ... -->) from the extracted text.
        Falls back to the full body only if neither heading is found.
        """
        import re

        lines = body_text.strip().splitlines()

        for heading in ("## reply body", "## email content"):
            in_content = False
            content_lines: list[str] = []

            for line in lines:
                if line.strip().lower().startswith(heading):
                    in_content = True
                    continue
                if in_content and line.strip().startswith("## "):
                    break
                if in_content:
                    content_lines.append(line)

            if content_lines:
                raw = "\n".join(content_lines)
                # Strip HTML comments (e.g. <!-- Write your reply here. -->)
                cleaned = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL).strip()
                if cleaned:
                    return cleaned

        # Fallback: use everything (should rarely happen)
        return body_text.strip()

    def _log_event(
        self, cid: str, action_type: str, target: str, result: str, details: str
    ) -> None:
        """Log an action executor event to the audit trail."""
        try:
            log_action(
                self.log_dir,
                {
                    "timestamp": now_iso(),
                    "correlation_id": cid,
                    "actor": "action_executor",
                    "action_type": action_type,
                    "target": target,
                    "result": result,
                    "parameters": {"details": details, "dev_mode": self.config.dev_mode},
                },
            )
        except Exception:
            logger.exception("Failed to log action executor event")

    def _log_odoo_event(
        self, cid: str, action_type: str, parameters: dict[str, Any]
    ) -> None:
        """Log an Odoo-specific event to vault/Logs/odoo/ and vault/Logs/actions/."""
        entry = {
            "timestamp": now_iso(),
            "correlation_id": cid,
            "actor": "action_executor",
            "action_type": action_type,
            "target": "odoo",
            "result": "success",
            "parameters": parameters,
        }
        # Write to Odoo-specific log
        odoo_log_dir = self.vault_path / "Logs" / "odoo"
        try:
            log_action(odoo_log_dir, entry)
        except Exception:
            logger.exception("Failed to write Odoo log")
        # Also write to general action log
        try:
            log_action(self.log_dir, entry)
        except Exception:
            logger.exception("Failed to write action log for Odoo event")
