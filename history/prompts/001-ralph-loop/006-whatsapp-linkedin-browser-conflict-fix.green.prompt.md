---
id: 006
title: WhatsApp & LinkedIn Browser Conflict Fix + Facebook Watcher Confirmation
stage: green
date: 2026-02-28
surface: agent
model: claude-sonnet-4-6
feature: 001-ralph-loop
branch: 001-ralph-loop
user: PMLS
command: /sp.implement (continuing)
labels: ["whatsapp","linkedin","facebook","playwright","browser-conflict","hitl","watcher","replier"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - backend/watchers/whatsapp_watcher.py
  - backend/watchers/linkedin_watcher.py
  - backend/watchers/facebook_watcher.py
  - backend/watchers/instagram_watcher.py
  - backend/watchers/twitter_watcher.py
  - backend/actions/whatsapp_replier.py
  - config/.env
tests:
  - Manual: facebook_watcher.py --once confirmed authenticated (23 notifications, 3 threads)
  - Manual: WhatsApp reply processed (vault/Approved cleared)
  - Manual: WhatsApp watcher resumed reading messages after selector fix
---

## Prompt

User ran LinkedIn watcher, got file in vault/Needs_Action. Wanted to understand how to reply using the LinkedIn message replier.

Subsequent issues:
1. vault/Approved/linkedin-reply and vault/Approved/whatsapp-reply files stuck (not processed by orchestrator)
2. "Browser closed too early" — replier couldn't send WhatsApp reply
3. WhatsApp watcher stopped reading messages after browser close-after-cycle fix
4. User proposed sequential browser usage pattern (watcher scans → closes → replier sends → closes)
5. User asked to confirm Facebook watcher is activated after logging in

## Response snapshot

**Root cause identified**: All watchers and repliers share the same Playwright persistent context profile directory (e.g., `config/whatsapp_session`). Chrome only allows ONE process to hold a profile lock at a time. When the watcher kept the browser open continuously, the replier couldn't open the same profile → "Target page, context or browser has been closed".

**Fix applied — Close-after-cycle pattern (all 5 watchers)**:
```python
while True:
    try:
        items = await self.check_for_updates()
        for item in items:
            await self.create_action_file(item)
    except Exception:
        self.logger.exception("Error in %s polling cycle", self.__class__.__name__)
    finally:
        await self._close_browser()   # ← releases profile lock
    await asyncio.sleep(self.check_interval)
```

**WhatsApp Business DOM fix** — `CHAT_LOADED_SELECTOR` updated to include:
```python
CHAT_LOADED_SELECTOR = ", ".join([
    'div[data-testid="chat-list"]',
    'div[aria-label="Chat list"]',
    "#pane-side",
    'div[role="listitem"]',
    'div[role="row"]',                        # WhatsApp Business (66 elements confirmed)
    'div[data-testid="chat-list-search"]',
])
```
Timeout increased from 30000ms → 60000ms.

**WhatsApp replier fixes**:
- `_check_session_state()`: Expanded to 8 selectors including `div[role="row"]`
- `_find_and_open_chat()`: Added `div[role="row"]` to row scan + `span[title]` name matching + `ArrowDown+Enter` keyboard fallback
- `_ensure_browser()`: Added single retry with 25s wait for profile-lock race condition
- `send_reply()`: Wait time 8s → 12s, 3-attempt retry loop

**config/.env**: `WHATSAPP_CHECK_INTERVAL=30` → `WHATSAPP_CHECK_INTERVAL=120`

**Facebook confirmed active**: `python backend/watchers/facebook_watcher.py --once` output:
```
Found 23 Facebook notification elements
Found 3 Facebook message threads
Facebook: found 0 notifications + 0 messages matching keywords
```
Session authenticated, scanning correctly. 0 matches because no messages contained configured keywords at test time.

## Outcome

- ✅ Impact: All 5 watchers now release browser profile after each scan cycle, enabling sequential (non-conflicting) browser usage with repliers
- 🧪 Tests: Facebook --once confirmed; WhatsApp reply manually verified (Approved folder cleared); watcher resumed after selector fix
- 📁 Files: 7 files modified (5 watchers + 1 replier + config)
- 🔁 Next prompts: Monitor orchestrator logs to verify stable WhatsApp loop; potentially tune check intervals per platform
- 🧠 Reflection: WhatsApp Business uses different DOM structure than standard WhatsApp Web — `div[role="row"]` is the canonical chat-list element. Always confirm live selectors via debug screenshots/logs before assuming standard selectors work.

## Evaluation notes (flywheel)

- Failure modes observed: Profile-lock race condition between watcher and replier; WhatsApp Business DOM divergence from standard WA Web; timeout too short (30s) for WhatsApp Business fresh browser open
- Graders run and results (PASS/FAIL): Manual verification PASS — reply sent, watcher reading, Facebook authenticated
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): Add per-platform browser profile separation (e.g., `config/whatsapp_watcher_session` vs `config/whatsapp_replier_session`) if conflicts persist at shorter intervals
