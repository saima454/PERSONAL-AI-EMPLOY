"""Facebook Messenger replier — sends approved replies via Messenger (Playwright).

This is an ACTION layer component. It reads approved facebook_reply files from
vault/Approved/, finds the Messenger conversation by sender name, and sends the reply.

Privacy: Reply content is drafted and approved locally. Only the final approved
text is sent to Facebook Messenger.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.utils.frontmatter import extract_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso
from backend.utils.uuid_utils import correlation_id

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parents[2]
load_dotenv(dotenv_path=_PROJECT_ROOT / "config" / ".env", override=True)

# Messenger selectors
SELECTORS = {
    "search_box":  'input[placeholder*="Search" i]',
    "search_box2": 'input[aria-label*="Search" i]',
    "thread_row":  '[role="main"] [role="row"]',
    "msg_input":   'div[role="textbox"][contenteditable="true"]',
    "send_button": 'button[aria-label*="Send" i]',
}

MESSENGER_URL = "https://www.facebook.com/messages/"


def _extract_reply_body(content: str) -> str:
    """Return the text below '## Reply Body' in the vault file."""
    marker = "## Reply Body"
    idx = content.find(marker)
    if idx == -1:
        return ""
    body = content[idx + len(marker):].strip()
    # Strip HTML comment placeholders
    lines = [
        line for line in body.splitlines()
        if not line.strip().startswith("<!--")
    ]
    return "\n".join(lines).strip()


class FacebookReplier:
    """Sends a Facebook Messenger reply for an approved vault file."""

    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/meta_session",
        headless: bool = False,
        dry_run: bool = True,
        dev_mode: bool = True,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.session_path = Path(session_path)
        self.headless = headless
        self.dry_run = dry_run
        self.dev_mode = dev_mode
        self.logs_path = self.vault_path / "Logs"
        self._context = None
        self._page = None
        self._playwright = None

    # ── Browser ──────────────────────────────────────────────────────

    async def _launch_browser(self) -> None:
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self.session_path.mkdir(parents=True, exist_ok=True)
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.session_path),
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )

    async def _close_browser(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _ensure_browser(self) -> None:
        if self._page is None or self._context is None:
            try:
                await self._launch_browser()
            except Exception as exc:
                logger.warning("Browser launch failed (profile may be briefly locked): %s — retrying in 25s", exc)
                await asyncio.sleep(25)
                await self._launch_browser()

    # ── Navigation ───────────────────────────────────────────────────

    async def _navigate_to_messenger(self) -> None:
        assert self._page is not None
        logger.debug("Navigating to Messenger...")
        await self._page.goto(MESSENGER_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(5)

    # ── Find & open conversation ──────────────────────────────────────

    async def _find_and_open_conversation(self, sender: str) -> bool:
        """Search Messenger for sender name and open the conversation. Returns True on success."""
        assert self._page is not None

        # Strategy 1: direct row scan in sidebar
        sidebar_sel = 'div[aria-label*="Chats" i] [role="row"]'
        try:
            rows = await self._page.query_selector_all(sidebar_sel)
            for row in rows[:40]:
                try:
                    text = (await row.inner_text()).strip()
                    if sender.lower() in text.lower():
                        await row.click()
                        await asyncio.sleep(2)
                        logger.info("Opened conversation via sidebar: %s", sender)
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        # Strategy 2: use the search box
        for search_sel in [SELECTORS["search_box"], SELECTORS["search_box2"]]:
            try:
                search = await self._page.query_selector(search_sel)
                if search:
                    await search.click()
                    await asyncio.sleep(0.5)
                    await search.fill(sender)
                    await asyncio.sleep(2)
                    # Click first search result
                    results = await self._page.query_selector_all(SELECTORS["thread_row"])
                    if results:
                        await results[0].click()
                        await asyncio.sleep(2)
                        logger.info("Opened conversation via search: %s", sender)
                        return True
                    # Keyboard fallback
                    await self._page.keyboard.press("ArrowDown")
                    await asyncio.sleep(0.5)
                    await self._page.keyboard.press("Enter")
                    await asyncio.sleep(2)
                    logger.info("Opened conversation via keyboard fallback: %s", sender)
                    return True
            except Exception:
                pass

        logger.error("Could not find Messenger conversation for: %s", sender)
        return False

    # ── Send message ─────────────────────────────────────────────────

    async def _send_message(self, text: str) -> bool:
        """Type and send text in the open conversation. Returns True on success."""
        assert self._page is not None

        msg_input = None
        for sel in [SELECTORS["msg_input"]]:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    msg_input = el
                    break
            except Exception:
                pass

        if not msg_input:
            logger.error("Could not find Messenger message input box")
            return False

        await msg_input.click()
        await asyncio.sleep(0.5)
        await msg_input.fill(text)
        await asyncio.sleep(1)

        # Try send button, fall back to Enter key
        sent = False
        try:
            send_btn = await self._page.query_selector(SELECTORS["send_button"])
            if send_btn:
                await send_btn.click()
                sent = True
        except Exception:
            pass

        if not sent:
            await self._page.keyboard.press("Enter")
            sent = True

        await asyncio.sleep(2)
        logger.info("Message sent via Messenger")
        return sent

    # ── Public API ───────────────────────────────────────────────────

    async def send_reply(self, file_path: Path, fm: dict[str, Any]) -> None:
        """Read the approved file, find the conversation, and send the reply."""
        sender = fm.get("sender", "")
        if not sender:
            raise ValueError(f"No sender in {file_path.name}")

        content = file_path.read_text(encoding="utf-8")
        reply_body = _extract_reply_body(content)
        if not reply_body:
            raise ValueError(f"Empty reply body in {file_path.name}")

        cid = correlation_id()

        if self.dev_mode or self.dry_run:
            logger.info(
                "[%s] Would send Facebook reply to %r: %r",
                "DEV_MODE" if self.dev_mode else "DRY_RUN",
                sender,
                reply_body[:80],
            )
            log_action(
                self.logs_path / "actions",
                {
                    "timestamp": now_iso(),
                    "correlation_id": cid,
                    "actor": "facebook_replier",
                    "action_type": "facebook_reply",
                    "target": sender,
                    "result": "dry_run",
                    "parameters": {"sender": sender, "preview": reply_body[:80]},
                },
            )
            return

        await self._ensure_browser()
        await self._navigate_to_messenger()

        found = await self._find_and_open_conversation(sender)
        if not found:
            raise RuntimeError(f"Could not find Messenger conversation for: {sender}")

        sent = await self._send_message(reply_body)
        if not sent:
            raise RuntimeError(f"Failed to send Messenger message to: {sender}")

        log_action(
            self.logs_path / "actions",
            {
                "timestamp": now_iso(),
                "correlation_id": cid,
                "actor": "facebook_replier",
                "action_type": "facebook_reply",
                "target": sender,
                "result": "success",
                "parameters": {"sender": sender, "preview": reply_body[:80]},
            },
        )
        logger.info("Facebook reply sent to %s", sender)
