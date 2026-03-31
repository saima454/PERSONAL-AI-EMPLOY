"""WhatsApp replier — sends approved replies via WhatsApp Web (Playwright).

This is an ACTION layer component. It reads approved whatsapp_reply files from
vault/Approved/, finds the chat by name on WhatsApp Web, and sends the reply.

Privacy: Reply content is drafted and approved locally. Only the final approved
text is sent to WhatsApp.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.utils.frontmatter import extract_frontmatter, update_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso
from backend.utils.uuid_utils import correlation_id

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parents[2]
load_dotenv(dotenv_path=_PROJECT_ROOT / "config" / ".env", override=True)

# WhatsApp Web selectors (mirrors whatsapp_watcher.py)
SELECTORS = {
    "qr_code": 'canvas[aria-label*="Scan this QR code"]',
    "qr_code_fallback": 'div[data-testid="qrcode"]',
    "chat_list": 'div[data-testid="chat-list"]',
    "chat_list_aria": 'div[aria-label="Chat list"]',
    "chat_list_pane": "#pane-side",
    "chat_row": 'div[data-testid="cell-frame-container"]',
    "chat_name_span": 'span[dir="auto"][title]',
    "search_box": 'div[data-testid="chat-list-search"]',
    "search_input": 'div[contenteditable="true"][data-tab="3"]',
    "conversation_header": 'div[data-testid="conversation-header"] span[dir="auto"]',
    # Message input & send
    "msg_input": 'div[data-testid="conversation-compose-box-input"]',
    "msg_input_fallback": 'div[contenteditable="true"][data-tab="10"]',
    "msg_input_aria": 'div[role="textbox"][contenteditable="true"]',
    "send_button": 'button[data-testid="send"]',
    "send_button_aria": 'button[aria-label="Send"]',
}


class WhatsAppReplier:
    """Sends approved WhatsApp replies from the vault."""

    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/whatsapp_session",
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ):
        self.vault_path = Path(vault_path)
        self.approved_path = self.vault_path / "Approved"
        self.done_path = self.vault_path / "Done"
        self.logs_path = self.vault_path / "Logs"
        self.session_path = Path(session_path)
        self.headless = headless
        self.dry_run = dry_run
        self.dev_mode = dev_mode
        self.logger = logging.getLogger(self.__class__.__name__)
        self._playwright = None
        self._context = None
        self._page = None

    # ── Browser Management ──────────────────────────────────────────

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
        if self._page is not None and self._context is not None:
            return
        # Watcher closes its browser after each scan, so the profile should be
        # free during its sleep window. One retry handles the rare overlap case
        # where the replier starts exactly as the watcher's scan begins (~20s).
        try:
            await self._launch_browser()
        except Exception as exc:
            self.logger.warning(
                "Browser launch failed (profile may be briefly locked): %s — retrying in 25s", exc
            )
            await asyncio.sleep(25)
            await self._launch_browser()

    # ── Navigation & Session ────────────────────────────────────────

    async def _navigate_and_wait(self, url: str, wait_seconds: float = 8.0) -> None:
        assert self._page is not None
        await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(wait_seconds)

    async def _save_debug_screenshot(self, label: str = "debug") -> None:
        if self._page is None:
            return
        try:
            path = self.logs_path / f"debug_{label}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            await self._page.screenshot(path=str(path), full_page=False)
            self.logger.info("Screenshot saved: %s", path)
        except Exception:
            pass

    async def _check_session_state(self) -> str:
        """Returns: 'ready', 'qr_code', 'loading', 'unknown'."""
        assert self._page is not None

        # Check for QR code (not logged in)
        for sel in [SELECTORS["qr_code"], SELECTORS["qr_code_fallback"]]:
            try:
                if await self._page.query_selector(sel):
                    return "qr_code"
            except Exception:
                pass

        # Check for loading screen
        try:
            if await self._page.query_selector('div[data-testid="startup"]'):
                return "loading"
        except Exception:
            pass

        # Check for chat list (logged in) — broad set covers WhatsApp Business Web
        # which uses different DOM structure than regular WhatsApp Web.
        ready_selectors = [
            SELECTORS["chat_list"],           # div[data-testid="chat-list"]
            SELECTORS["chat_list_aria"],       # div[aria-label="Chat list"]
            SELECTORS["chat_list_pane"],       # #pane-side
            SELECTORS["search_box"],           # div[data-testid="chat-list-search"]
            SELECTORS["chat_row"],             # div[data-testid="cell-frame-container"]
            'div[role="listitem"]',            # generic chat rows
            'div[aria-label="Search or start a new chat"]',
            'div[aria-label="Chat list"]',
        ]
        for sel in ready_selectors:
            try:
                if await self._page.query_selector(sel):
                    return "ready"
            except Exception:
                pass

        return "unknown"

    # ── Reply Logic ─────────────────────────────────────────────────

    async def _find_and_open_chat(self, chat_name: str) -> bool:
        """Find a chat by name and open it.

        Strategy:
        1. Try to find the chat row directly in the visible list by matching name
        2. Fall back to using the search box
        Returns True if the chat was found and opened.

        Selector notes (from live diagnostic):
          - WhatsApp Business uses div[role="row"] — NOT div[data-testid="cell-frame-container"]
          - Chat names are in span[title] inside those rows
        """
        assert self._page is not None
        chat_name_lower = chat_name.lower()
        self.logger.info("Looking for WhatsApp chat: %s", chat_name)

        # Strategy 1: scan visible chat rows.
        # WhatsApp Business uses div[role="row"]; standard WA uses cell-frame-container / listitem.
        row_selectors = [
            SELECTORS["chat_row"],    # div[data-testid="cell-frame-container"] — standard WA
            'div[role="listitem"]',   # standard WA
            'div[role="row"]',        # WhatsApp Business (confirmed 66 elements in diagnostic)
            "#pane-side li",
        ]
        for row_sel in row_selectors:
            try:
                rows = await self._page.query_selector_all(row_sel)
                if not rows:
                    continue
                self.logger.debug("Strategy 1: scanning %d rows via '%s'", len(rows), row_sel)
                for row in rows[:80]:
                    try:
                        # span[title] works for both standard WA and WA Business
                        for span_sel in ['span[title]', SELECTORS["chat_name_span"]]:
                            name_el = await row.query_selector(span_sel)
                            if name_el:
                                title = await name_el.get_attribute("title") or ""
                                if title and chat_name_lower in title.lower():
                                    self.logger.info("Found chat '%s' via title — clicking", chat_name)
                                    await row.click()
                                    await asyncio.sleep(2)
                                    return True
                        # Fallback: full inner text of the row
                        text = (await row.inner_text()).strip().lower()
                        if chat_name_lower in text:
                            self.logger.info("Found chat '%s' via text match — clicking", chat_name)
                            await row.click()
                            await asyncio.sleep(2)
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

        # Strategy 2: use the search box.
        # Try multiple search input selectors — WA Business may differ from standard WA.
        self.logger.info("Chat not in visible list — trying search box")
        search_input_selectors = [
            SELECTORS["search_input"],               # div[contenteditable="true"][data-tab="3"]
            'div[data-testid="chat-list-search"] div[contenteditable="true"]',
            'div[contenteditable="true"][title]',
            'div[role="textbox"]',
        ]
        for search_sel in search_input_selectors:
            try:
                el = await self._page.query_selector(search_sel)
                if not el or not await el.is_visible():
                    continue

                self.logger.info("Found search input via: %s", search_sel)
                await el.click()
                await asyncio.sleep(0.5)
                await self._page.keyboard.type(chat_name, delay=50)
                await asyncio.sleep(3)  # wait for results to render

                # Attempt A: click first result by selector (covers all DOM variants)
                result_selectors = [
                    SELECTORS["chat_row"],   # div[data-testid="cell-frame-container"]
                    'div[role="listitem"]',
                    'div[role="row"]',       # WhatsApp Business main list & search results
                    'div[data-testid="search-result"]',
                ]
                clicked = False
                for res_sel in result_selectors:
                    results = await self._page.query_selector_all(res_sel)
                    if results:
                        self.logger.info("Search returned %d results via '%s' — clicking first", len(results), res_sel)
                        await results[0].click()
                        await asyncio.sleep(2)
                        clicked = True
                        break

                if not clicked:
                    # Attempt B: keyboard navigation — ArrowDown selects the first
                    # result in the list regardless of DOM structure, then Enter opens it.
                    self.logger.info("No result selector matched — using ArrowDown+Enter")
                    await self._page.keyboard.press("ArrowDown")
                    await asyncio.sleep(0.5)
                    await self._page.keyboard.press("Enter")
                    await asyncio.sleep(2)
                    clicked = True

                if clicked:
                    try:
                        await self._page.keyboard.press("Escape")
                    except Exception:
                        pass
                    self.logger.info("Opened chat via search for '%s'", chat_name)
                    return True
                break
            except Exception:
                pass

        self.logger.warning("Could not find WhatsApp chat for: %s", chat_name)
        await self._save_debug_screenshot("replier_chat_not_found")
        return False

    async def _type_and_send(self, text: str) -> bool:
        """Type reply text into the message input and send it."""
        assert self._page is not None
        self.logger.info("Typing reply (%d chars)...", len(text))

        input_selectors = [
            SELECTORS["msg_input"],
            SELECTORS["msg_input_fallback"],
            SELECTORS["msg_input_aria"],
            'div[contenteditable="true"]',
        ]

        typed = False
        for sel in input_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el and await el.is_visible():
                    self.logger.info("Found message input via: %s", sel)
                    await el.click()
                    await asyncio.sleep(0.3)
                    await self._page.keyboard.type(text, delay=20)
                    self.logger.info("Typed %d chars", len(text))
                    typed = True
                    break
            except Exception as exc:
                self.logger.debug("Input '%s' error: %s", sel, exc)

        if not typed:
            self.logger.error("Could not find message input")
            await self._save_debug_screenshot("replier_input_not_found")
            return False

        await asyncio.sleep(0.5)

        # Click send button
        for send_sel in [SELECTORS["send_button"], SELECTORS["send_button_aria"]]:
            try:
                el = await self._page.query_selector(send_sel)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(1)
                    self.logger.info("Clicked send button")
                    return True
            except Exception as exc:
                self.logger.debug("Send button '%s' error: %s", send_sel, exc)

        # Keyboard fallback
        self.logger.info("Send button not found — pressing Enter")
        try:
            await self._page.keyboard.press("Enter")
            await asyncio.sleep(1)
            return True
        except Exception as exc:
            self.logger.error("Enter key fallback failed: %s", exc)

        await self._save_debug_screenshot("replier_send_failed")
        return False

    async def send_reply(self, chat_name: str, reply_text: str) -> bool:
        """Send a WhatsApp reply to the chat matching chat_name.

        Returns True on success (or in dev_mode/dry_run).
        """
        assert self._page is not None

        if self.dev_mode:
            self.logger.info(
                "[DEV_MODE] Would reply to '%s' (%d chars): %s",
                chat_name, len(reply_text), reply_text[:100],
            )
            return True

        if self.dry_run:
            self.logger.info(
                "[DRY RUN] Would reply to '%s' (%d chars)", chat_name, len(reply_text)
            )
            return True

        self.logger.info("=" * 60)
        self.logger.info("SENDING WHATSAPP REPLY to '%s' (%d chars)", chat_name, len(reply_text))
        self.logger.info("=" * 60)

        await self._navigate_and_wait("https://web.whatsapp.com/", wait_seconds=12.0)

        # WhatsApp Business can take longer to render — retry state check up to 3x
        state = "unknown"
        for attempt in range(3):
            state = await self._check_session_state()
            if state == "ready":
                break
            if state == "qr_code":
                break
            self.logger.debug("Session state '%s' on attempt %d — waiting 5s", state, attempt + 1)
            await asyncio.sleep(5)

        if state != "ready":
            self.logger.error(
                "WhatsApp not logged in (state=%s). Cannot send reply.", state
            )
            await self._save_debug_screenshot("replier_not_logged_in")
            return False

        if not await self._find_and_open_chat(chat_name):
            return False

        if not await self._type_and_send(reply_text):
            return False

        self.logger.info("=" * 60)
        self.logger.info("REPLY SENT to '%s'", chat_name)
        self.logger.info("=" * 60)
        return True

    # ── Body Extraction ─────────────────────────────────────────────

    @staticmethod
    def _extract_reply_body(body_text: str) -> str:
        """Extract content from '## Reply Body' section, stripping HTML comments."""
        import re

        lines = body_text.strip().splitlines()
        in_content = False
        content_lines: list[str] = []

        for line in lines:
            if line.strip().lower().startswith("## reply body"):
                in_content = True
                continue
            if in_content and line.strip().startswith("## "):
                break
            if in_content:
                content_lines.append(line)

        if content_lines:
            raw = "\n".join(content_lines)
            cleaned = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL).strip()
            if cleaned:
                return cleaned

        return body_text.strip()

    # ── File Lifecycle ──────────────────────────────────────────────

    def _move_to_done(self, file_path: Path, result: str) -> None:
        self.done_path.mkdir(parents=True, exist_ok=True)
        dest = self.done_path / file_path.name
        try:
            update_frontmatter(file_path, {
                "status": "done",
                "completed_at": now_iso(),
                "result": result,
            })
        except Exception:
            self.logger.warning("Could not update frontmatter on %s", file_path.name)
        shutil.move(str(file_path), str(dest))
        self.logger.info("Moved %s to Done/ (result: %s)", file_path.name, result)

    # ── Main Entry Point ────────────────────────────────────────────

    async def process_reply_file(self, file_path: Path) -> bool:
        """Process a single approved whatsapp_reply file.

        Returns True on success (reply sent or dry_run/dev_mode).
        """
        content = file_path.read_text(encoding="utf-8")
        fm, body_text = extract_frontmatter(content)

        chat_name = fm.get("chat_name", "")
        if not chat_name:
            self.logger.error("No chat_name in %s — cannot reply", file_path.name)
            return False

        reply_text = self._extract_reply_body(body_text)
        if not reply_text:
            self.logger.error("Empty reply body in %s — skipping", file_path.name)
            return False

        cid = correlation_id()
        self.logger.info(
            "Sending WhatsApp reply to '%s' from %s (%d chars)",
            chat_name, file_path.name, len(reply_text),
        )

        await self._ensure_browser()
        success = await self.send_reply(chat_name, reply_text)

        log_action(
            self.logs_path / "actions",
            {
                "timestamp": now_iso(),
                "correlation_id": cid,
                "actor": "whatsapp_replier",
                "action_type": "whatsapp_reply",
                "target": file_path.name,
                "result": "success" if success else "failure",
                "parameters": {
                    "chat_name": chat_name,
                    "reply_length": len(reply_text),
                    "dry_run": self.dry_run,
                    "dev_mode": self.dev_mode,
                },
            },
        )

        if success:
            self._move_to_done(file_path, "success")
        else:
            self.logger.error("Failed to send WhatsApp reply for %s", file_path.name)

        return success
