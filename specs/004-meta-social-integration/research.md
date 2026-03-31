# Research: Meta Social Integration (004)

**Status**: Complete — all NEEDS CLARIFICATION resolved
**Date**: 2026-02-21
**Feature**: 004-meta-social-integration

---

## Decision 1: Session Architecture — Shared vs. Separate

**Decision**: Single shared Playwright persistent context at `config/meta_session/` for both Facebook and Instagram.

**Rationale**: Playwright's `launch_persistent_context()` stores cookies for ALL domains visited in that browser session. When the operator logs into both `facebook.com` and `instagram.com` (or uses "Continue with Facebook" on Instagram) during the one-time setup, both domains' cookies are persisted in the same directory. This:
- Reduces operator friction to a single setup step
- Mirrors the existing `config/linkedin_session/` pattern
- Keeps the `config/` layout consistent

**Alternatives considered**:
- **Separate directories** (`config/facebook_session/`, `config/instagram_session/`): Requires two separate `--setup` runs. No security benefit. Rejected.
- **Meta Graph API**: Requires a Facebook App and granular permission approval through Meta's App Review. Personal account access severely restricted post-2018. OAuth token refresh requires server infrastructure. Rejected — overkill for a personal AI employee.
- **Third-party scraping services**: Sends user data externally. Violates Constitution Principle I (local-first). Rejected.

---

## Decision 2: Browser Automation Strategy

**Decision**: Playwright with broad, resilient CSS selectors — same strategy as `linkedin_watcher.py`.

**Rationale**: The LinkedIn watcher (`backend/watchers/linkedin_watcher.py`) proves this approach works for heavy SPAs:
1. URL-based session detection first (`/login`, `/checkpoint/challenge` in URL)
2. Broad element probes (try specific selectors, fall back to broader ones)
3. Skip malformed elements rather than crashing
4. Save debug screenshots on failure for operator inspection

Facebook and Instagram are both heavy SPAs that change their class names frequently. Broad selectors (text-based, aria-label, structural) are more resilient than specific BEM class names.

**Alternatives considered**:
- **Specific CSS selectors only**: Breaks every time the platform updates. Rejected.
- **XPath**: More verbose, no meaningful resilience benefit over broad CSS. Rejected.

---

## Decision 3: ActionExecutor Routing

**Decision**: Extend the existing `HANDLERS` dict in `ActionExecutor` (`backend/orchestrator/action_executor.py:29`) with two new entries:
```python
"facebook_post": "_handle_facebook_post",
"instagram_post": "_handle_instagram_post",
```

**Rationale**: The existing dispatch pattern (`fm.get("type")` → handler method) is the canonical approach per the codebase. No architectural change needed — this is a pure extension with zero risk of regression.

**Alternatives considered**: N/A — canonical extension point.

---

## Decision 4: ContentScheduler Platform Extension

**Decision**: Add an optional `platform` field to each topic dict in `Content_Strategy.md`. `PostGenerator.generate()` reads `topic.get("platform", "linkedin")` and sets `type: {platform}_post` in draft frontmatter.

**Rationale**:
- Minimal diff to feature 003 (backward-compatible: omitting `platform` defaults to `linkedin`)
- No schema migration needed — existing topics without `platform` continue to work
- Single source of truth for platform selection remains the strategy file

**Extension to Content_Strategy.md** (per-topic optional field):
```yaml
topics:
  - name: "AI in Business"
    platform: linkedin        # existing topics, no change needed
  - name: "Behind the Scenes"
    platform: facebook        # new
  - name: "Visual Story"
    platform: instagram       # new
```

**Alternatives considered**:
- Separate strategy files per platform: More isolation but doubles operator configuration. Rejected.
- Derive platform from topic name keywords: Fragile heuristic. Rejected.

---

## Decision 5: Image Attachment Support

**Decision**: Optional `image_path` frontmatter field. Poster validates path exists before publishing. Missing image → move to `vault/Rejected/`.

**Validation rules**:
- If `image_path` is absent: publish text-only post (valid for both Facebook and Instagram)
- If `image_path` is present and file missing: reject with `image_file_not_found` error
- If `image_path` is present and file exists: upload alongside post text

**Rationale**: Simple, explicit, testable. No server-side image hosting needed.

**Alternatives considered**: Base64-embedded images in frontmatter: Too large for markdown files. Rejected.

---

## Decision 6: Deduplication Storage

**Decision**: Separate JSON dedup files per watcher:
- `vault/Logs/processed_facebook.json`
- `vault/Logs/processed_instagram.json`

Same schema and 7-day retention as `processed_linkedin.json`.

**Rationale**: Independent files mean a corrupt Facebook dedup store doesn't affect Instagram monitoring. Isolated failure modes, easier debugging.

**Dedup key format**: `"{sender}|{text[:100]}|{timestamp}"` — same as LinkedIn watcher.

---

## Decision 7: Polling Intervals

**Decision**:
- Facebook watcher: default 120 seconds (`FACEBOOK_CHECK_INTERVAL=120`)
- Instagram watcher: default 60 seconds (`INSTAGRAM_CHECK_INTERVAL=60`)

**Rationale**:
- Facebook's notification page is heavier (more DOM elements) and updates less frequently in real-time; 120s is conservative and safe
- Instagram notifications update faster; 60s is a reasonable minimum
- Both are configurable via env vars per the existing pattern
- Neither violates Constitution Principle VI (rate limits): these are read-only polls, not write operations

---

## Decision 8: Session Setup UX

**Decision**: A single `--setup` command per watcher opens a headed browser at `config/meta_session/`. The operator can log into both Facebook and Instagram in the same browser window (shared directory), then presses Enter.

**Setup flow**:
1. `python backend/watchers/facebook_watcher.py --setup`
2. Browser opens at `facebook.com`
3. Operator logs in → optionally navigates to `instagram.com` → logs in
4. Operator presses Enter in terminal
5. Browser waits 30s for cookie persistence, then closes

**Rationale**: Matches LinkedIn's established setup UX. Operators familiar with LinkedIn setup will immediately understand it. The Facebook setup command is the entry point; Instagram benefits from the same session.

---

## Resolved Unknowns

| Unknown | Resolution |
|---------|------------|
| Shared vs. separate Meta session | Shared `config/meta_session/` (Decision 1) |
| Scraping approach | Playwright broad selectors (Decision 2) |
| ActionExecutor extension point | Extend HANDLERS dict (Decision 3) |
| ContentScheduler backward-compat | Optional `platform` field, default `linkedin` (Decision 4) |
| Image attachments | Optional `image_path` frontmatter, validate before publish (Decision 5) |
| Dedup storage | Separate JSON files per watcher (Decision 6) |
| Polling intervals | FB: 120s, IG: 60s, both configurable (Decision 7) |
| Setup UX | Single `--setup` command per watcher, shared session dir (Decision 8) |
