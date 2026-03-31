"""Instagram watcher — monitors Instagram notifications and DMs via Playwright.

This is a PERCEPTION layer component. It observes Instagram and writes action
files to the vault. It never posts, replies, or modifies Instagram state.

Shared Meta session: uses config/meta_session/ (same directory as Facebook).
Run with --setup for first-time login; session is then reused automatically.

Privacy: All data is processed locally. No data is sent externally.

Usage:
    # First-time setup (headed browser for manual login)
    uv run python backend/watchers/instagram_watcher.py --setup

    # Continuous polling
    uv run python backend/watchers/instagram_watcher.py

    # Single check
    uv run python backend/watchers/instagram_watcher.py --once
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.utils.frontmatter import create_file_with_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import format_filename_timestamp, is_within_hours, now_iso
from backend.utils.uuid_utils import correlation_id, short_id
from backend.watchers.base_watcher import BaseWatcher

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "urgent",
    "collab",
    "invoice",
    "project",
    "partnership",
    "opportunity",
    "meeting",
    "deadline",
]

HIGH_PRIORITY_KEYWORDS = {"urgent", "invoice", "deadline"}
MEDIUM_PRIORITY_KEYWORDS = {"collab", "project", "partnership", "opportunity", "meeting"}

PROCESSED_IDS_RETENTION_DAYS = 7
MAX_NOTIFICATIONS = 20
MAX_DMS = 15


def _slugify(text: str, max_length: int = 40) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_length].rstrip("-")


def _classify_priority(text: str, keywords: list[str]) -> tuple[str, str | None]:
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            kw_lower = kw.lower()
            if kw_lower in HIGH_PRIORITY_KEYWORDS:
                return "high", kw
            if kw_lower in MEDIUM_PRIORITY_KEYWORDS:
                return "medium", kw
            return "low", kw
    return "low", None


def _make_dedup_key(sender: str, text: str, timestamp: str) -> str:
    return f"{sender}|{text[:100]}|{timestamp}"


class InstagramWatcher(BaseWatcher):
    """Watches Instagram notifications and DMs, creates vault action files."""

    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/meta_session",
        check_interval: int = 60,
        keywords: list[str] | None = None,
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ) -> None:
        super().__init__(vault_path, check_interval)
        self.session_path = Path(session_path)
        self.keywords = keywords or DEFAULT_KEYWORDS[:]
        self.headless = headless
        self.dry_run = dry_run
        self.dev_mode = dev_mode
        self.processed_ids_path = self.logs_path / "processed_instagram.json"
        self._processed_ids: dict[str, str] = {}
        self._last_cleanup: str | None = None
        self._consecutive_errors = 0
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
        if hasattr(self, "_playwright") and self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _ensure_browser(self) -> None:
        if self._page is None or self._context is None:
            await self._launch_browser()

    async def _navigate_and_wait(self, url: str, wait_seconds: float = 8.0) -> None:
        assert self._page is not None
        self.logger.debug("Navigating to %s ...", url)
        await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            self.logger.debug("Network idle not reached within 15s, continuing")
        await asyncio.sleep(wait_seconds)

    async def _save_debug_screenshot(self, label: str = "debug") -> None:
        if self._page is None:
            return
        try:
            screenshot_path = self.logs_path / f"debug_screenshot_ig_{label}.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await self._page.screenshot(path=str(screenshot_path), full_page=False)
            self.logger.info("Debug screenshot saved: %s", screenshot_path)
        except Exception:
            self.logger.debug("Could not save debug screenshot", exc_info=True)

    # ── Session State ───────────────────────────────────────────────

    async def _check_session_state(self) -> str:
        """Returns: 'ready', 'login_required', 'captcha', 'unknown'."""
        assert self._page is not None
        current_url = self._page.url
        self.logger.debug("Checking Instagram session state, URL: %s", current_url)

        # URL-based detection (most reliable)
        if "/challenge" in current_url or "captcha" in current_url.lower():
            return "captcha"
        if "/accounts/login" in current_url or "/login" in current_url:
            return "login_required"

        # DOM-based login form check
        for sel in [
            'input[name="username"]',
            'input[name="password"]',
            'form[action*="login"]',
        ]:
            try:
                if await self._page.query_selector(sel):
                    return "login_required"
            except Exception:
                pass

        if await self._is_authenticated():
            return "ready"
        return "unknown"

    async def _is_authenticated(self) -> bool:
        """Check if user is logged into Instagram."""
        assert self._page is not None
        current_url = self._page.url

        is_ig_page = "instagram.com" in current_url
        if not is_ig_page:
            return False

        auth_selectors = [
            '[aria-label="Home"]',                  # home nav icon
            '[aria-label*="profile" i]',            # profile link
            '[aria-label*="Direct" i]',             # DM icon
            'svg[aria-label*="Home" i]',            # home SVG
            'div[role="navigation"]',               # main nav
            '[aria-label*="Search" i]',             # search
        ]
        for sel in auth_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    self.logger.debug("Instagram auth via selector: %s", sel)
                    return True
            except Exception:
                continue

        # Broad element count heuristic
        try:
            buttons = await self._page.query_selector_all("button")
            links = await self._page.query_selector_all("a")
            total = len(buttons) + len(links)
            if total > 20:
                self.logger.debug("Instagram auth via element count (%d)", total)
                return True
        except Exception:
            pass

        return False

    async def setup_session(self) -> bool:
        """Interactive setup: open headed browser for manual Instagram login."""
        self.logger.info("Starting Instagram session setup (headed mode)...")

        original_headless = self.headless
        self.headless = False

        try:
            await self._launch_browser()
            await self._navigate_and_wait(
                "https://www.instagram.com/", wait_seconds=5.0
            )

            state = await self._check_session_state()
            self.logger.info("Initial Instagram session state: %s", state)

            if state == "ready":
                self.logger.info(
                    "Already logged in to Instagram! Waiting 10s to ensure session is saved..."
                )
                await asyncio.sleep(10)
                return True

            self.logger.info(
                "\n"
                "  ┌─────────────────────────────────────────────────┐\n"
                "  │         Instagram Session Setup                  │\n"
                "  ├─────────────────────────────────────────────────┤\n"
                "  │                                                  │\n"
                "  │  1. Log in with your Instagram credentials       │\n"
                "  │     (or use 'Continue with Facebook' if logged   │\n"
                "  │      into Facebook in the same session)          │\n"
                "  │  2. Complete any 2FA or CAPTCHA challenges       │\n"
                "  │  3. Wait until you can see your Instagram feed   │\n"
                "  │                                                  │\n"
                "  │  >>> Press ENTER in this terminal when done <<<  │\n"
                "  │                                                  │\n"
                "  └─────────────────────────────────────────────────┘\n"
            )

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input)

            self.logger.info("User confirmed. Verifying Instagram session...")
            await asyncio.sleep(2)
            state = await self._check_session_state()
            self.logger.info("Post-login Instagram session state: %s", state)

            if state == "ready":
                self.logger.info(
                    "Login confirmed! Waiting 30s to persist session to %s ...",
                    self.session_path,
                )
                await asyncio.sleep(30)
                self.logger.info("Instagram session saved successfully!")
                return True

            self.logger.error(
                "Instagram login verification failed. Current URL: %s", self._page.url
            )
            return False

        finally:
            self.headless = original_headless
            await self._close_browser()

    # ── Processed IDs ───────────────────────────────────────────────

    def _load_processed_ids(self) -> None:
        if not self.processed_ids_path.exists():
            self._processed_ids = {}
            self._last_cleanup = None
            return
        try:
            data = json.loads(self.processed_ids_path.read_text(encoding="utf-8"))
            self._processed_ids = data.get("processed_ids", {})
            self._last_cleanup = data.get("last_cleanup")
        except (json.JSONDecodeError, KeyError):
            self.logger.warning("Corrupted processed_instagram.json, starting fresh")
            self._processed_ids = {}
            self._last_cleanup = None

    def _save_processed_ids(self) -> None:
        self.processed_ids_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "processed_ids": self._processed_ids,
            "last_cleanup": self._last_cleanup or now_iso(),
        }
        self.processed_ids_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _cleanup_old_ids(self) -> None:
        now = now_iso()
        if self._last_cleanup and is_within_hours(self._last_cleanup, 24):
            return
        cutoff = []
        for key, processed_at in self._processed_ids.items():
            try:
                if not is_within_hours(processed_at, PROCESSED_IDS_RETENTION_DAYS * 24):
                    cutoff.append(key)
            except (ValueError, TypeError):
                cutoff.append(key)
        for key in cutoff:
            del self._processed_ids[key]
        self._last_cleanup = now
        if cutoff:
            self.logger.info("Cleaned up %d old Instagram processed IDs", len(cutoff))

    # ── Notification Scanning ───────────────────────────────────────

    async def _scan_notifications(self) -> list[dict[str, Any]]:
        """Navigate to Instagram activity page and extract notification items."""
        assert self._page is not None

        self.logger.info("Scanning Instagram notifications...")
        await self._navigate_and_wait(
            "https://www.instagram.com/activity/", wait_seconds=8.0
        )

        state = await self._check_session_state()
        if state in ("login_required", "captcha"):
            self.logger.error(
                "Instagram session expired or CAPTCHA. Run --setup to re-login. (state=%s)",
                state,
            )
            await self._save_debug_screenshot("ig_notifications_auth_fail")
            self._log_error("instagram", f"session_{state}")
            return []

        notification_selectors = [
            'main section > div > div',
            'main [role="list"] li',
            "main article",
            "main li",
            'div[role="button"]',
        ]

        cards: list = []
        used_selector = ""
        for sel in notification_selectors:
            try:
                cards = await self._page.query_selector_all(sel)
                self.logger.debug("IG notification probe '%s': %d matches", sel, len(cards))
                if 0 < len(cards) <= 100:
                    used_selector = sel
                    break
                cards = []
            except Exception:
                pass

        if not cards:
            self.logger.info("No Instagram notification elements found")
            await self._save_debug_screenshot("ig_notifications_empty")
            return []

        self.logger.info(
            "Found %d Instagram notification elements via '%s'",
            len(cards),
            used_selector,
        )

        cards = cards[:MAX_NOTIFICATIONS]
        items: list[dict[str, Any]] = []

        for card in cards:
            try:
                text = (await card.inner_text()).strip()
                if not text or len(text) < 5:
                    continue

                time_el = await card.query_selector("time")
                time_str = ""
                if time_el:
                    time_str = (await time_el.inner_text()).strip()

                actor = ""
                for actor_sel in ["a span", "strong", "a"]:
                    actor_el = await card.query_selector(actor_sel)
                    if actor_el:
                        actor = (await actor_el.inner_text()).strip()
                        if actor and len(actor) < 60:
                            break
                        actor = ""

                priority, matched_keyword = _classify_priority(text, self.keywords)
                if matched_keyword is None:
                    continue

                dedup_key = _make_dedup_key(actor or "instagram", text, time_str)
                if dedup_key in self._processed_ids:
                    continue

                self.logger.info(
                    "Matched IG notification: actor='%s', keyword='%s'",
                    actor,
                    matched_keyword,
                )

                items.append({
                    "item_type": "notification",
                    "sender": actor or "Instagram",
                    "preview": text[:500],
                    "time": time_str,
                    "priority": priority,
                    "matched_keyword": matched_keyword,
                    "dedup_key": dedup_key,
                    "needs_reply": False,
                })
            except Exception:
                self.logger.debug("Failed to extract Instagram notification", exc_info=True)

        return items

    # ── DM Scanning ─────────────────────────────────────────────────

    async def _scan_direct_messages(self) -> list[dict[str, Any]]:
        """Navigate to Instagram Direct inbox and extract keyword-matching threads."""
        assert self._page is not None

        self.logger.info("Scanning Instagram DMs...")
        await self._navigate_and_wait(
            "https://www.instagram.com/direct/inbox/", wait_seconds=8.0
        )

        state = await self._check_session_state()
        if state in ("login_required", "captcha"):
            self.logger.error(
                "Instagram session expired on DMs page. (state=%s)", state
            )
            await self._save_debug_screenshot("ig_dms_auth_fail")
            self._log_error("instagram", f"dms_session_{state}")
            return []

        thread_selectors = [
            '[role="listbox"] > div',
            'div[class*="thread"]',
            '[role="list"] > div',
            "main li",
            "main article",
        ]

        threads: list = []
        used_selector = ""
        for sel in thread_selectors:
            try:
                threads = await self._page.query_selector_all(sel)
                self.logger.debug("IG DM probe '%s': %d matches", sel, len(threads))
                if 0 < len(threads) <= 50:
                    used_selector = sel
                    break
                threads = []
            except Exception:
                pass

        if not threads:
            self.logger.info("No Instagram DM threads found")
            return []

        self.logger.info(
            "Found %d Instagram DM threads via '%s'", len(threads), used_selector
        )

        threads = threads[:MAX_DMS]
        items: list[dict[str, Any]] = []

        for thread in threads:
            try:
                full_text = (await thread.inner_text()).strip()
                if not full_text or len(full_text) < 3:
                    continue

                lines = [line.strip() for line in full_text.split("\n") if line.strip()]

                sender = ""
                for sender_sel in ["h3", "h4", "strong", "a span", "a"]:
                    sender_el = await thread.query_selector(sender_sel)
                    if sender_el:
                        sender = (await sender_el.inner_text()).strip()
                        if sender and len(sender) < 60:
                            break
                        sender = ""
                if not sender and lines:
                    sender = lines[0][:50]

                preview = ""
                for prev_sel in ["p", "span", '[class*="snippet"]']:
                    prev_el = await thread.query_selector(prev_sel)
                    if prev_el:
                        preview = (await prev_el.inner_text()).strip()
                        if preview:
                            break
                if not preview:
                    preview = " ".join(lines[1:]) if len(lines) > 1 else full_text

                time_str = ""
                time_el = await thread.query_selector("time")
                if time_el:
                    time_str = (await time_el.inner_text()).strip()

                search_text = f"{sender} {preview}"
                priority, matched_keyword = _classify_priority(search_text, self.keywords)
                if matched_keyword is None:
                    continue

                dedup_key = _make_dedup_key(sender, preview, time_str)
                if dedup_key in self._processed_ids:
                    continue

                items.append({
                    "item_type": "direct_message",
                    "sender": sender or "Unknown",
                    "preview": preview[:500],
                    "time": time_str,
                    "priority": priority,
                    "matched_keyword": matched_keyword,
                    "dedup_key": dedup_key,
                    "needs_reply": True,
                })
            except Exception:
                self.logger.debug("Failed to extract Instagram DM thread", exc_info=True)

        return items

    # ── Core Watcher Logic ──────────────────────────────────────────

    async def check_for_updates(self) -> list[dict[str, Any]]:
        """Return new Instagram notifications and DMs matching keywords.

        DEV_MODE: returns synthetic item without launching browser.
        Session missing: logs warning, returns [].
        Never raises.
        """
        # DEV_MODE short-circuit
        if self.dev_mode:
            self.logger.info("[DEV_MODE] InstagramWatcher: returning synthetic item")
            return [
                {
                    "item_type": "notification",
                    "sender": "[DEV_MODE]",
                    "preview": "[DEV_MODE] Synthetic Instagram notification for testing",
                    "time": "just now",
                    "priority": "low",
                    "matched_keyword": "dev",
                    "dedup_key": f"[DEV_MODE]|ig_synthetic|{now_iso()}",
                    "needs_reply": False,
                }
            ]

        # Session guard
        if not self.session_path.exists():
            self.logger.warning(
                "Meta session not found at %s — run --setup to initialize",
                self.session_path,
            )
            return []

        self._load_processed_ids()
        self._cleanup_old_ids()

        try:
            await self._ensure_browser()
            notifications = await self._scan_notifications()
            dms = await self._scan_direct_messages()
            items = notifications + dms
            self._consecutive_errors = 0
            self.logger.info(
                "Instagram: found %d notifications + %d DMs matching keywords",
                len(notifications),
                len(dms),
            )
            return items
        except Exception:
            self._consecutive_errors += 1
            self.logger.exception(
                "Error scanning Instagram (consecutive errors: %d)",
                self._consecutive_errors,
            )
            await self._save_debug_screenshot("ig_scan_error")
            self._log_error("instagram", "scan_failed")
            return []

    async def create_action_file(self, item: dict[str, Any]) -> Path | None:
        """Create vault/Needs_Action/INSTAGRAM_*.md for a matched item."""
        sender_slug = _slugify(item["sender"])
        timestamp = format_filename_timestamp()
        filename = f"INSTAGRAM_{sender_slug}_{timestamp}.md"
        file_path = self.needs_action / filename

        ig_id = f"INSTAGRAM_{short_id()}_{timestamp}"

        frontmatter: dict[str, Any] = {
            "type": "instagram",
            "id": ig_id,
            "source": "instagram_watcher",
            "item_type": item["item_type"],
            "sender": item["sender"],
            "preview": item["preview"][:200],
            "received": now_iso(),
            "priority": item["priority"],
            "status": "pending",
        }
        if item.get("matched_keyword"):
            frontmatter["matched_keyword"] = item["matched_keyword"]
        if item.get("needs_reply"):
            frontmatter["needs_reply"] = True

        body = f"""
## Instagram {item["item_type"].replace("_", " ").title()}

**From:** {item["sender"]}
**Type:** {item["item_type"]}
**Time:** {item.get("time", "unknown")}
**Priority:** {item["priority"]} (keyword: {item.get("matched_keyword", "unknown")})

## Content

{item["preview"]}

## Suggested Actions

- [ ] Review on Instagram
- [ ] Reply if needed
- [ ] Mark as processed
"""

        cid = correlation_id()

        if self.dry_run:
            self.logger.info(
                "[DRY RUN] Would create: %s (priority: %s, from: %s)",
                filename,
                item["priority"],
                item["sender"],
            )
            log_action(
                self.logs_path / "actions",
                {
                    "timestamp": now_iso(),
                    "correlation_id": cid,
                    "actor": "instagram_watcher",
                    "action_type": "instagram_detected",
                    "target": filename,
                    "result": "dry_run",
                    "parameters": {
                        "item_type": item["item_type"],
                        "sender": item["sender"],
                        "priority": item["priority"],
                        "dry_run": True,
                        "dev_mode": self.dev_mode,
                    },
                },
            )
            return None

        self.needs_action.mkdir(parents=True, exist_ok=True)
        create_file_with_frontmatter(file_path, frontmatter, body)

        self._processed_ids[item["dedup_key"]] = now_iso()
        self._save_processed_ids()

        log_action(
            self.logs_path / "actions",
            {
                "timestamp": now_iso(),
                "correlation_id": cid,
                "actor": "instagram_watcher",
                "action_type": "instagram_processed",
                "target": filename,
                "result": "success",
                "parameters": {
                    "item_type": item["item_type"],
                    "sender": item["sender"],
                    "priority": item["priority"],
                    "dev_mode": self.dev_mode,
                },
            },
        )

        self.logger.info(
            "Created action file: %s (priority: %s)", filename, item["priority"]
        )
        return file_path

    # ── Error Logging ───────────────────────────────────────────────

    def _log_error(self, target: str, error_msg: str) -> None:
        try:
            log_action(
                self.logs_path / "errors",
                {
                    "timestamp": now_iso(),
                    "correlation_id": correlation_id(),
                    "actor": "instagram_watcher",
                    "action_type": "error",
                    "target": target,
                    "error": error_msg,
                    "details": {
                        "consecutive_errors": self._consecutive_errors,
                        "dev_mode": self.dev_mode,
                    },
                    "result": "failure",
                },
            )
        except Exception:
            self.logger.exception("Failed to write Instagram error log")

    # ── Main Loop Override ──────────────────────────────────────────

    async def run(self) -> None:
        self.logger.info(
            "Starting InstagramWatcher (interval: %ds, dev_mode: %s)",
            self.check_interval,
            self.dev_mode,
        )
        try:
            if not self.dev_mode:
                await self._ensure_browser()
            while True:
                try:
                    items = await self.check_for_updates()
                    for item in items:
                        await self.create_action_file(item)
                except Exception:
                    self.logger.exception("Error in InstagramWatcher polling cycle")
                finally:
                    # Close browser after each cycle so the profile lock is released
                    # during the sleep window — prevents conflicts with action posters.
                    await self._close_browser()
                await asyncio.sleep(self.check_interval)
        finally:
            await self._close_browser()


# ── CLI Entry Point ──────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instagram Watcher - AI Employee Perception Layer"
    )
    parser.add_argument("--once", action="store_true", help="Single check and exit")
    parser.add_argument("--setup", action="store_true", help="First-time Instagram session setup")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    env_path = Path(__file__).resolve().parents[2] / "config" / ".env"
    load_dotenv(env_path)
    args = _parse_args(argv)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    vault_path = os.getenv("VAULT_PATH", "./vault")
    session_path = os.getenv("INSTAGRAM_SESSION_PATH", "config/meta_session")
    check_interval = int(os.getenv("INSTAGRAM_CHECK_INTERVAL", "60"))
    headless = os.getenv("INSTAGRAM_HEADLESS", "false").lower() == "true"
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"

    keywords_env = os.getenv("INSTAGRAM_KEYWORDS", "")
    keywords = [k.strip() for k in keywords_env.split(",") if k.strip()] or None

    watcher = InstagramWatcher(
        vault_path=vault_path,
        session_path=session_path,
        check_interval=check_interval,
        keywords=keywords,
        headless=headless,
        dry_run=dry_run,
        dev_mode=dev_mode,
    )

    if args.setup:
        logger.info("Starting Instagram session setup...")
        success = asyncio.run(watcher.setup_session())
        if success:
            logger.info("Setup complete! Session saved to %s", session_path)
        else:
            logger.error("Setup failed.")
        return

    if args.once:
        logger.info("Running single Instagram check...")

        async def single_check() -> None:
            try:
                items = await watcher.check_for_updates()
                for item in items:
                    await watcher.create_action_file(item)
                logger.info("Check complete. Found %d matching items.", len(items))
            finally:
                await watcher._close_browser()

        asyncio.run(single_check())
        return

    logger.info(
        "Starting Instagram watcher (interval: %ds, headless: %s, dev_mode: %s)",
        check_interval,
        headless,
        dev_mode,
    )
    asyncio.run(watcher.run())


if __name__ == "__main__":
    main()
