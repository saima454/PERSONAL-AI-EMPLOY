"""Instagram poster — publishes approved posts to Instagram via Playwright.

This is an ACTION layer component. It reads approved post files from the vault
and publishes them to Instagram. Posts MUST be human-approved (in vault/Approved/).

Privacy: Post content is drafted and approved locally. Only the final approved
caption is sent to Instagram.

Usage:
    # Post all approved Instagram posts
    uv run python backend/actions/instagram_poster.py --once

    # Continuous polling (checks every 5 minutes)
    uv run python backend/actions/instagram_poster.py
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
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

MAX_POSTS_PER_RUN = 5
INSTAGRAM_CHAR_LIMIT = 2_200
POST_CHECK_INTERVAL = 300  # 5 minutes

# Instagram post composer selectors (broad fallbacks)
POST_SELECTORS = {
    "create_button": [
        '[aria-label*="New post" i]',
        '[aria-label*="Create" i]',
        'svg[aria-label*="New post" i]',
        '[data-testid="new-post-button"]',
    ],
    "caption_editor": [
        'textarea[aria-label*="caption" i]',
        'textarea[placeholder*="caption" i]',
        'div[contenteditable="true"]',
        'div[role="textbox"]',
    ],
    "share_button": [
        'button[type="submit"]',
        '[aria-label*="Share" i]',
        'div[role="button"][aria-label*="share" i]',
    ],
}

AUTHENTICATED_SELECTORS = [
    '[aria-label="Home"]',
    '[aria-label*="Direct" i]',
    'nav[role="navigation"]',
    '[aria-label*="Search" i]',
    '[aria-label*="Explore" i]',
]


class InstagramPoster:
    """Publishes approved Instagram posts from the vault."""

    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/meta_session",
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.session_path = Path(session_path)
        self.approved_dir = self.vault_path / "Approved"
        self.done_dir = self.vault_path / "Done"
        self.rejected_dir = self.vault_path / "Rejected"
        self.log_dir = self.vault_path / "Logs" / "actions"
        self.headless = headless
        self.dry_run = dry_run
        self.dev_mode = dev_mode
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

    # ── Session State ───────────────────────────────────────────────

    async def _check_session_state(self) -> str:
        """Returns: 'ready', 'login_required', 'captcha', 'unknown'."""
        assert self._page is not None
        current_url = self._page.url

        if "/challenge" in current_url or "captcha" in current_url.lower():
            return "captcha"
        if "/accounts/login" in current_url or "/accounts/suspended" in current_url:
            return "login_required"

        for sel in ['input[name="username"]', 'input[name="password"]', 'form[action*="login"]']:
            try:
                if await self._page.query_selector(sel):
                    return "login_required"
            except Exception:
                pass

        for sel in AUTHENTICATED_SELECTORS:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    return "ready"
            except Exception:
                pass

        return "unknown"

    # ── Validation ──────────────────────────────────────────────────

    def _validate_post(self, body: str, fm: dict[str, Any]) -> str | None:
        """Return None if valid, or rejection_reason string if invalid."""
        if not body.strip():
            return "empty_body"

        if len(body) > INSTAGRAM_CHAR_LIMIT:
            logger.warning(
                "Instagram post exceeds %d char limit (%d chars)",
                INSTAGRAM_CHAR_LIMIT,
                len(body),
            )
            return "character_count_exceeded"

        image_path = fm.get("image_path", "")
        if image_path and not Path(image_path).exists():
            logger.warning("Image file not found: %s", image_path)
            return "image_file_not_found"

        return None

    # ── Publishing ──────────────────────────────────────────────────

    async def _publish_post(self, body: str, image_path: str = "") -> bool:
        """Navigate to Instagram and post caption. Returns True on success."""
        assert self._page is not None

        await self._page.goto(
            "https://www.instagram.com/", wait_until="domcontentloaded", timeout=60000
        )
        with contextlib.suppress(Exception):
            await self._page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(5)

        state = await self._check_session_state()
        if state != "ready":
            logger.error(
                "Instagram session not ready for posting (state=%s). Run --setup.", state
            )
            return False

        # Click the Create/New Post button
        create_clicked = False
        for sel in POST_SELECTORS["create_button"]:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
                    create_clicked = True
                    logger.debug("Clicked Instagram create button via '%s'", sel)
                    break
            except Exception:
                pass

        if not create_clicked:
            logger.error("Could not find Instagram create post button")
            return False

        # Upload image if provided (required for feed posts on Instagram)
        if image_path:
            try:
                file_input = await self._page.query_selector('input[type="file"]')
                if file_input:
                    await file_input.set_input_files(image_path)
                    await asyncio.sleep(3)
                    logger.info("Attached image: %s", image_path)
                else:
                    logger.warning("No file input found for image upload")
            except Exception:
                logger.warning("Could not attach image: %s", image_path, exc_info=True)

        # Find caption editor and type post text
        caption_found = False
        for sel in POST_SELECTORS["caption_editor"]:
            try:
                editor = await self._page.query_selector(sel)
                if editor:
                    await editor.click()
                    await asyncio.sleep(1)
                    await self._page.keyboard.type(body, delay=20)
                    caption_found = True
                    logger.debug("Typed caption via editor '%s'", sel)
                    break
            except Exception:
                pass

        if not caption_found:
            logger.error("Could not find Instagram caption editor")
            return False

        await asyncio.sleep(1)

        # Click Share button
        for sel in POST_SELECTORS["share_button"]:
            try:
                btn = await self._page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(3)
                    logger.info("Instagram post submitted successfully")
                    return True
            except Exception:
                pass

        logger.error("Could not find Instagram Share button")
        return False

    # ── File Lifecycle ──────────────────────────────────────────────

    def _move_to_done(self, file_path: Path, published_at: str) -> None:
        self.done_dir.mkdir(parents=True, exist_ok=True)
        dest = self.done_dir / file_path.name
        try:
            update_frontmatter(file_path, {"status": "done", "published_at": published_at})
        except Exception:
            logger.warning("Could not update frontmatter on %s", file_path.name)
        if file_path.exists():
            shutil.move(str(file_path), str(dest))

    def _move_to_rejected(self, file_path: Path, reason: str) -> None:
        self.rejected_dir.mkdir(parents=True, exist_ok=True)
        dest = self.rejected_dir / file_path.name
        try:
            update_frontmatter(
                file_path,
                {
                    "status": "rejected",
                    "rejected_at": now_iso(),
                    "rejection_reason": reason,
                },
            )
        except Exception:
            logger.warning("Could not update frontmatter on %s", file_path.name)
        if file_path.exists():
            shutil.move(str(file_path), str(dest))

    # ── Main Processing ─────────────────────────────────────────────

    def _scan_approved(self) -> list[tuple[Path, dict[str, Any], str]]:
        """List approved instagram_post files. Returns (path, frontmatter, body) tuples."""
        if not self.approved_dir.exists():
            return []

        results = []
        for md_file in sorted(self.approved_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
                fm, body = extract_frontmatter(content)
                if (
                    fm
                    and fm.get("status") == "approved"
                    and fm.get("type") == "instagram_post"
                ):
                    results.append((md_file, fm, body or ""))
            except (OSError, UnicodeDecodeError):
                logger.warning("Failed to read approval file: %s", md_file)
        return results

    async def process_approved_posts(self) -> int:
        """Process all approved instagram_post files. Returns count of processed posts."""
        posts = self._scan_approved()
        if not posts:
            logger.debug("No approved Instagram posts found")
            return 0

        posts = posts[:MAX_POSTS_PER_RUN]
        processed = 0

        for file_path, fm, body in posts:
            cid = correlation_id()
            logger.info("Processing Instagram post: %s", file_path.name)

            # Validate
            rejection_reason = self._validate_post(body, fm)
            if rejection_reason:
                logger.warning(
                    "Instagram post validation failed (%s): %s",
                    rejection_reason,
                    file_path.name,
                )
                self._move_to_rejected(file_path, rejection_reason)
                log_action(
                    self.log_dir,
                    {
                        "timestamp": now_iso(),
                        "correlation_id": cid,
                        "actor": "instagram_poster",
                        "action_type": "instagram_post_rejected",
                        "target": file_path.name,
                        "result": "failure",
                        "parameters": {"rejection_reason": rejection_reason},
                    },
                )
                processed += 1
                continue

            # DEV_MODE / dry_run
            if self.dev_mode or self.dry_run:
                mode = "[DEV_MODE]" if self.dev_mode else "[DRY RUN]"
                logger.info(
                    "%s Would post to Instagram: %s...",
                    mode,
                    body[:100].replace("\n", " "),
                )
                self._move_to_done(file_path, now_iso())
                log_action(
                    self.log_dir,
                    {
                        "timestamp": now_iso(),
                        "correlation_id": cid,
                        "actor": "instagram_poster",
                        "action_type": "instagram_post_published",
                        "target": file_path.name,
                        "result": "dev_mode",
                        "parameters": {
                            "dev_mode": self.dev_mode,
                            "dry_run": self.dry_run,
                            "char_count": len(body),
                        },
                    },
                )
                processed += 1
                continue

            # Real publish
            try:
                await self._ensure_browser()
                image_path = fm.get("image_path", "")
                success = await self._publish_post(body, image_path=image_path)
                published_at = now_iso()

                if success:
                    self._move_to_done(file_path, published_at)
                    log_action(
                        self.log_dir,
                        {
                            "timestamp": published_at,
                            "correlation_id": cid,
                            "actor": "instagram_poster",
                            "action_type": "instagram_post_published",
                            "target": file_path.name,
                            "result": "success",
                            "parameters": {"char_count": len(body)},
                        },
                    )
                    logger.info("Instagram post published: %s", file_path.name)
                else:
                    self._move_to_rejected(file_path, "publish_failed")
                    log_action(
                        self.log_dir,
                        {
                            "timestamp": published_at,
                            "correlation_id": cid,
                            "actor": "instagram_poster",
                            "action_type": "instagram_post_failed",
                            "target": file_path.name,
                            "result": "failure",
                            "parameters": {"rejection_reason": "publish_failed"},
                        },
                    )
                processed += 1

            except Exception:
                logger.exception("Unexpected error publishing Instagram post: %s", file_path.name)
                self._move_to_rejected(file_path, "publish_failed")
                processed += 1

        return processed


# ── CLI Entry Point ──────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instagram Poster - AI Employee Action Layer"
    )
    parser.add_argument("--once", action="store_true", help="Process approved posts and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
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
    headless = os.getenv("INSTAGRAM_HEADLESS", "true").lower() == "true"
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"

    poster = InstagramPoster(
        vault_path=vault_path,
        session_path=session_path,
        headless=headless,
        dry_run=dry_run,
        dev_mode=dev_mode,
    )

    async def run_once() -> None:
        try:
            count = await poster.process_approved_posts()
            logger.info("Instagram poster: processed %d posts", count)
        finally:
            await poster._close_browser()

    if args.once:
        asyncio.run(run_once())
        return

    # Continuous polling loop
    async def run_continuous() -> None:
        logger.info("Starting Instagram poster (interval: %ds)", POST_CHECK_INTERVAL)
        try:
            while True:
                try:
                    await poster.process_approved_posts()
                except Exception:
                    logger.exception("Error in Instagram poster cycle")
                await asyncio.sleep(POST_CHECK_INTERVAL)
        finally:
            await poster._close_browser()

    asyncio.run(run_continuous())


if __name__ == "__main__":
    main()
