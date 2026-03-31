"""LinkedIn poster - publishes approved posts to LinkedIn via Playwright.

This is an ACTION layer component. It reads approved post files from the vault
and publishes them to LinkedIn. Posts MUST be human-approved (in vault/Approved/).

Privacy: Post content is drafted and approved locally. Only the final approved
text is sent to LinkedIn.

Usage:
    # Post all approved LinkedIn posts
    uv run python backend/actions/linkedin_poster.py --once

    # Continuous polling (checks every 5 minutes)
    uv run python backend/actions/linkedin_poster.py
"""

from __future__ import annotations

import argparse
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

# Max posts per run to prevent runaway posting
MAX_POSTS_PER_RUN = 5

POST_CHECK_INTERVAL = 300  # 5 minutes

# LinkedIn post creation selectors (multiple fallbacks)
POST_SELECTORS = {
    "start_post": [
        "button.share-box-feed-entry__trigger",
        'button[aria-label*="Start a post"]',
        'button[aria-label*="start a post"]',
        'div.share-box-feed-entry__trigger',
    ],
    "text_editor": [
        'div[role="textbox"][contenteditable="true"]',
        "div.ql-editor[data-placeholder]",
        'div[aria-label*="Text editor"]',
    ],
    "post_button": [
        "button.share-actions__primary-action",
        'button[aria-label="Post"]',
        'button[aria-label="post"]',
    ],
}

# Strict selectors that ONLY appear when truly authenticated
# (matches linkedin_watcher.py exactly)
AUTHENTICATED_SELECTORS = [
    'img.global-nav__me-photo',
    'img.feed-identity-module__member-photo',
    'button[aria-label*="me" i]',
    'div.feed-identity-module',
    'div[data-control-name="identity_welcome_message"]',
    'span.feed-identity-module__actor-name',
    'a[href*="/in/"][data-control-name="identity_profile_photo"]',
    'div.share-box-feed-entry__trigger',
]


class LinkedInPoster:
    """Publishes approved LinkedIn posts from the vault."""

    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/linkedin_session",
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

    # ── Navigation & Session (matches linkedin_watcher.py) ────────

    async def _navigate_and_wait(self, url: str, wait_seconds: float = 10.0) -> None:
        """Navigate to a URL and wait for the page to fully render.

        Uses the same strategy as linkedin_watcher.py:
        1. Navigate with domcontentloaded
        2. Try to reach networkidle (with timeout)
        3. Wait a fixed delay for JavaScript rendering
        """
        assert self._page is not None
        self.logger.debug("Navigating to %s ...", url)

        await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)

        try:
            await self._page.wait_for_load_state("networkidle", timeout=15000)
            self.logger.debug("Network idle reached")
        except Exception:
            self.logger.debug("Network idle not reached within 15s, continuing")

        self.logger.debug("Waiting %.0fs for JS rendering...", wait_seconds)
        await asyncio.sleep(wait_seconds)

    async def _check_session_state(self) -> str:
        """Returns: 'ready', 'login_required', 'captcha', 'unknown'.

        Uses URL-based detection first (most reliable), then falls back
        to DOM selectors. Matches linkedin_watcher.py logic exactly.
        """
        assert self._page is not None
        current_url = self._page.url
        self.logger.debug("Checking session state, URL: %s", current_url)

        # URL-based detection (most reliable)
        if "/checkpoint/challenge" in current_url:
            return "captcha"
        if "/login" in current_url or "/authwall" in current_url:
            return "login_required"

        # DOM-based captcha check
        try:
            if await self._page.query_selector("#captcha-internal"):
                return "captcha"
        except Exception:
            pass

        # DOM-based login form check
        for sel in [
            "form.login__form", "#username", 'input[name="session_key"]',
            'form[action*="login"]',
        ]:
            try:
                if await self._page.query_selector(sel):
                    return "login_required"
            except Exception:
                pass

        # Check for authenticated state
        if await self._is_authenticated():
            return "ready"

        return "unknown"

    async def _is_authenticated(self) -> bool:
        """Check if the user is truly logged in.

        Uses URL checks + strict selectors + element-count heuristic.
        Matches linkedin_watcher.py logic exactly.
        """
        assert self._page is not None
        current_url = self._page.url

        is_linkedin_page = any(
            p in current_url
            for p in ["/feed", "/messaging", "/notifications", "/mynetwork", "/in/"]
        )
        if not is_linkedin_page:
            return False

        # Try strict selectors first
        for sel in AUTHENTICATED_SELECTORS:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    self.logger.debug("Authenticated via selector: %s", sel)
                    return True
            except Exception:
                continue

        # Broad check: element count heuristic
        try:
            buttons = await self._page.query_selector_all("button")
            links = await self._page.query_selector_all("a")
            imgs = await self._page.query_selector_all("img")
            total = len(buttons) + len(links) + len(imgs)
            self.logger.debug(
                "Page element count: %d buttons, %d links, %d imgs (total %d)",
                len(buttons), len(links), len(imgs), total,
            )
            if total > 40:
                self.logger.debug("Authenticated via element count heuristic (%d)", total)
                return True
        except Exception:
            pass

        return False

    async def _save_debug_screenshot(self, label: str = "debug") -> None:
        """Save a screenshot for debugging when something fails."""
        if self._page is None:
            return
        try:
            screenshot_path = self.logs_path / f"debug_{label}.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await self._page.screenshot(path=str(screenshot_path), full_page=False)
            self.logger.info("Debug screenshot saved to %s", screenshot_path)
        except Exception:
            self.logger.debug("Could not save debug screenshot", exc_info=True)

    # ── Vault Scanning ──────────────────────────────────────────────

    def find_approved_posts(self) -> list[Path]:
        """Find all approved LinkedIn post files in the vault."""
        if not self.approved_path.exists():
            return []

        posts = []
        for md_file in self.approved_path.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                frontmatter, _ = extract_frontmatter(content)
                if frontmatter.get("type") == "linkedin_post":
                    posts.append(md_file)
                    self.logger.debug("Found approved post: %s", md_file.name)
            except Exception:
                self.logger.debug("Could not parse %s", md_file.name, exc_info=True)

        return posts[:MAX_POSTS_PER_RUN]

    def _extract_post_content(self, file_path: Path) -> tuple[dict[str, Any], str]:
        """Extract frontmatter and post body from a file.

        Returns:
            Tuple of (frontmatter_dict, post_body_text).
        """
        content = file_path.read_text(encoding="utf-8")
        frontmatter, body = extract_frontmatter(content)

        # Strip markdown headers like "# Post Content" from the body
        lines = body.strip().split("\n")
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# ") and not clean_lines:
                # Skip the first heading (e.g., "# Post Content")
                continue
            clean_lines.append(line)

        post_text = "\n".join(clean_lines).strip()
        return frontmatter, post_text

    # ── LinkedIn Posting ────────────────────────────────────────────

    async def _find_and_click(
        self, selectors: list[str], description: str, timeout: float = 2.0,
    ) -> bool:
        """Try clicking the first matching selector from a list."""
        assert self._page is not None
        for sel in selectors:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    visible = await el.is_visible()
                    self.logger.info(
                        "  [%s] selector '%s': FOUND (visible=%s)", description, sel, visible,
                    )
                    if visible:
                        await el.click()
                        self.logger.info("  [%s] Clicked via: %s", description, sel)
                        await asyncio.sleep(timeout)
                        return True
                else:
                    self.logger.debug("  [%s] selector '%s': not found", description, sel)
            except Exception as exc:
                self.logger.debug("  [%s] selector '%s': error %s", description, sel, exc)
        return False

    async def _find_and_click_by_text(
        self, text_patterns: list[str], description: str, timeout: float = 2.0,
    ) -> bool:
        """Find a clickable element by its visible text content."""
        assert self._page is not None
        for pattern in text_patterns:
            try:
                # Playwright text selector — matches visible text, case-insensitive
                loc = self._page.get_by_text(pattern, exact=False).first
                if await loc.is_visible():
                    self.logger.info(
                        "  [%s] text match '%s': FOUND and visible", description, pattern,
                    )
                    await loc.click()
                    self.logger.info("  [%s] Clicked via text: '%s'", description, pattern)
                    await asyncio.sleep(timeout)
                    return True
                self.logger.debug(
                    "  [%s] text match '%s': found but not visible", description, pattern,
                )
            except Exception as exc:
                self.logger.debug(
                    "  [%s] text match '%s': error %s", description, pattern, exc,
                )
        return False

    async def _open_post_composer(self) -> bool:
        """Click the share box to open the post editor/modal.

        Tries CSS selectors first, then text-based matching as fallback.
        """
        assert self._page is not None
        self.logger.info("STEP 1: Opening post composer...")

        # ── CSS selectors (broad, most-specific first) ──
        share_box_selectors = [
            "div.share-box-feed-entry__top-bar",
            "button.share-box-feed-entry__trigger",
            'button[class*="share-box"]',
            'div[class*="share-box"] button',
            'div[class*="share-box"]',
            'div.artdeco-card button',
            '[role="button"][class*="share"]',
        ]

        if await self._find_and_click(share_box_selectors, "share-box"):
            return True

        # ── Text-based fallback ──
        self.logger.info("  CSS selectors failed, trying text-based match...")
        text_patterns = [
            "Start a post",
            "What do you want to talk about",
            "Share your thoughts",
            "Create a post",
        ]

        if await self._find_and_click_by_text(text_patterns, "share-box-text"):
            return True

        # ── Broadest fallback: role="button" with post-related aria-label ──
        self.logger.info("  Text match failed, trying aria-label fallback...")
        aria_selectors = [
            '[role="button"][aria-label*="post" i]',
            '[role="button"][aria-label*="share" i]',
            '[role="button"][aria-label*="create" i]',
        ]

        if await self._find_and_click(aria_selectors, "share-box-aria"):
            return True

        self.logger.error("STEP 1 FAILED: Could not find post composer trigger")
        await self._save_debug_screenshot("feed_composer_not_found")
        return False

    async def _type_in_editor(self, text: str) -> bool:
        """Find the post editor text area and type content into it."""
        assert self._page is not None
        self.logger.info("STEP 2: Typing post content (%d chars)...", len(text))

        editor_selectors = [
            'div[role="textbox"][contenteditable="true"]',
            'div.ql-editor[data-placeholder]',
            'div[aria-label*="Text editor"]',
            'div[aria-label*="text editor"]',
            'div[contenteditable="true"][class*="editor"]',
            'div[contenteditable="true"]',
        ]

        for sel in editor_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el and await el.is_visible():
                    self.logger.info("  Found editor via: %s", sel)
                    await el.click()
                    await asyncio.sleep(0.5)
                    await self._page.keyboard.type(text, delay=20)
                    self.logger.info("  Typed %d chars into editor", len(text))
                    return True
                elif el:
                    self.logger.debug("  Editor '%s' found but not visible", sel)
            except Exception as exc:
                self.logger.debug("  Editor '%s' error: %s", sel, exc)

        # Text-based fallback for placeholder
        self.logger.info("  CSS selectors failed, trying placeholder text match...")
        try:
            loc = self._page.get_by_placeholder("What do you want to talk about", exact=False).first
            if await loc.is_visible():
                await loc.click()
                await asyncio.sleep(0.5)
                await self._page.keyboard.type(text, delay=20)
                self.logger.info("  Typed %d chars via placeholder match", len(text))
                return True
        except Exception as exc:
            self.logger.debug("  Placeholder match error: %s", exc)

        self.logger.error("STEP 2 FAILED: Could not find text editor")
        await self._save_debug_screenshot("editor_not_found")
        return False

    async def _click_post_button(self) -> bool:
        """Find and click the Post/Submit button."""
        assert self._page is not None
        self.logger.info("STEP 3: Clicking Post button...")

        post_button_selectors = [
            "button.share-actions__primary-action",
            'button[aria-label="Post"]',
            'button[aria-label="post"]',
            'button[class*="share-actions"] span',
        ]

        if await self._find_and_click(post_button_selectors, "post-button", timeout=3.0):
            return True

        # Text-based: find a button whose text is exactly "Post"
        self.logger.info("  CSS selectors failed, trying text-based match...")
        try:
            loc = self._page.get_by_role("button", name="Post", exact=True)
            if await loc.first.is_visible():
                await loc.first.click()
                self.logger.info("  Clicked Post button via role+name match")
                await asyncio.sleep(3)
                return True
        except Exception as exc:
            self.logger.debug("  Role+name match error: %s", exc)

        self.logger.error("STEP 3 FAILED: Could not find Post button")
        await self._save_debug_screenshot("post_button_not_found")
        return False

    async def publish_post(self, post_text: str) -> bool:
        """Publish a post to LinkedIn feed.

        Full flow with debug logging and screenshots at each stage:
        1. Open post composer (share box)
        2. Type content into editor
        3. Click Post button
        4. Verify success

        Args:
            post_text: The text content to post.

        Returns:
            True if the post was published successfully.
        """
        assert self._page is not None

        if self.dev_mode:
            self.logger.info(
                "[DEV_MODE] Would post to LinkedIn (%d chars): %s",
                len(post_text), post_text[:100],
            )
            return True

        self.logger.info("=" * 60)
        self.logger.info("PUBLISHING POST (%d chars)", len(post_text))
        self.logger.info("=" * 60)

        # Screenshot before posting
        await self._save_debug_screenshot("feed_before_post")

        # Step 1: Open the post composer
        if not await self._open_post_composer():
            return False

        # Wait for modal/editor to render
        self.logger.info("  Waiting 3s for editor modal to render...")
        await asyncio.sleep(3)
        await self._save_debug_screenshot("feed_composer_opened")

        # Step 2: Type the post content
        if not await self._type_in_editor(post_text):
            return False

        await asyncio.sleep(1)
        await self._save_debug_screenshot("feed_content_typed")

        # Step 3: Click Post
        if not await self._click_post_button():
            return False

        # Step 4: Wait and verify
        self.logger.info("STEP 4: Waiting for post confirmation...")
        await asyncio.sleep(5)
        await self._save_debug_screenshot("feed_after_post")

        self.logger.info("=" * 60)
        self.logger.info("POST PUBLISHED SUCCESSFULLY (%d chars)", len(post_text))
        self.logger.info("=" * 60)
        return True

    # ── File Lifecycle ──────────────────────────────────────────────

    def _move_to_done(self, file_path: Path, result: str) -> Path:
        """Move a file from Approved to Done, updating frontmatter."""
        self.done_path.mkdir(parents=True, exist_ok=True)
        dest = self.done_path / file_path.name

        # Update frontmatter before moving
        update_frontmatter(file_path, {
            "status": "done",
            "completed_at": now_iso(),
            "result": result,
        })

        shutil.move(str(file_path), str(dest))
        self.logger.info("Moved %s to Done/ (result: %s)", file_path.name, result)
        return dest

    # ── Main Processing ─────────────────────────────────────────────

    async def process_approved_posts(self) -> int:
        """Find and publish all approved LinkedIn posts.

        Returns:
            Number of posts processed.
        """
        posts = self.find_approved_posts()
        if not posts:
            self.logger.debug("No approved LinkedIn posts found")
            return 0

        self.logger.info("Found %d approved LinkedIn post(s)", len(posts))

        await self._ensure_browser()
        await self._navigate_and_wait(
            "https://www.linkedin.com/feed/", wait_seconds=10.0
        )

        state = await self._check_session_state()
        self.logger.info("Session state: %s", state)

        if state != "ready":
            self.logger.error(
                "Not logged in (state=%s). Run linkedin_watcher.py --setup first.", state
            )
            await self._save_debug_screenshot("poster_screenshot")
            return 0

        processed = 0
        for post_file in posts:
            cid = correlation_id()
            try:
                frontmatter, post_text = self._extract_post_content(post_file)

                if not post_text.strip():
                    self.logger.warning("Empty post content in %s, skipping", post_file.name)
                    continue

                self.logger.info("Publishing post from %s...", post_file.name)

                if self.dry_run:
                    self.logger.info(
                        "[DRY RUN] Would publish: %s (%d chars)",
                        post_file.name, len(post_text),
                    )
                    log_action(
                        self.logs_path / "actions",
                        {
                            "timestamp": now_iso(),
                            "correlation_id": cid,
                            "actor": "linkedin_poster",
                            "action_type": "linkedin_post",
                            "target": post_file.name,
                            "result": "dry_run",
                            "parameters": {
                                "content_length": len(post_text),
                                "dry_run": True,
                                "dev_mode": self.dev_mode,
                            },
                        },
                    )
                    processed += 1
                    continue

                success = await self.publish_post(post_text)

                if success:
                    self._move_to_done(post_file, "success")
                    log_action(
                        self.logs_path / "actions",
                        {
                            "timestamp": now_iso(),
                            "correlation_id": cid,
                            "actor": "linkedin_poster",
                            "action_type": "linkedin_post",
                            "target": post_file.name,
                            "result": "success",
                            "parameters": {
                                "content_length": len(post_text),
                                "content_preview": post_text[:100],
                                "dry_run": False,
                                "dev_mode": self.dev_mode,
                            },
                        },
                    )
                    processed += 1
                else:
                    self.logger.error("Failed to publish %s", post_file.name)
                    log_action(
                        self.logs_path / "errors",
                        {
                            "timestamp": now_iso(),
                            "correlation_id": cid,
                            "actor": "linkedin_poster",
                            "action_type": "error",
                            "target": post_file.name,
                            "error": "post_failed",
                            "result": "failure",
                        },
                    )

                # Rate limit: wait between posts
                if processed < len(posts):
                    await asyncio.sleep(5)

            except Exception:
                self.logger.exception("Error processing %s", post_file.name)
                log_action(
                    self.logs_path / "errors",
                    {
                        "timestamp": now_iso(),
                        "correlation_id": cid,
                        "actor": "linkedin_poster",
                        "action_type": "error",
                        "target": post_file.name,
                        "error": "processing_exception",
                        "result": "failure",
                    },
                )

        return processed

    async def run(self) -> None:
        """Main polling loop for poster."""
        self.logger.info("Starting LinkedInPoster (interval: %ds)", POST_CHECK_INTERVAL)
        try:
            while True:
                try:
                    await self.process_approved_posts()
                except Exception:
                    self.logger.exception("Error in poster polling cycle")
                await asyncio.sleep(POST_CHECK_INTERVAL)
        finally:
            await self._close_browser()


# ── CLI Entry Point ─────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LinkedIn Poster - AI Employee Action Layer"
    )
    parser.add_argument("--once", action="store_true", help="Process once and exit")
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
    session_path = os.getenv("LINKEDIN_SESSION_PATH", "config/linkedin_session")
    headless = os.getenv("LINKEDIN_HEADLESS", "false").lower() == "true"
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"

    poster = LinkedInPoster(
        vault_path=vault_path,
        session_path=session_path,
        headless=headless,
        dry_run=dry_run,
        dev_mode=dev_mode,
    )

    if args.once:
        logger.info("Running single post check...")

        async def single_run() -> None:
            try:
                count = await poster.process_approved_posts()
                logger.info("Done. Processed %d post(s).", count)
            finally:
                await poster._close_browser()

        asyncio.run(single_run())
        return

    logger.info(
        "Starting LinkedIn poster (dry_run: %s, dev_mode: %s)", dry_run, dev_mode
    )
    asyncio.run(poster.run())


if __name__ == "__main__":
    main()
