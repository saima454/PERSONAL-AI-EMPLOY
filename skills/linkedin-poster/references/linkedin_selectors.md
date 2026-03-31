# LinkedIn Web Selectors Reference

LinkedIn's DOM uses a mix of semantic HTML, class-based selectors, and
data attributes. Unlike WhatsApp Web, LinkedIn uses more standard HTML
patterns but changes class names frequently.

**Last verified:** 2026-02-12

## Important Note

LinkedIn aggressively detects automation. Use realistic delays between
actions and avoid rapid-fire interactions. Selectors below prioritize
semantic HTML and aria attributes over class names.

## Session State Detection

| Purpose | Selector | Notes |
|---------|----------|-------|
| Login form | `form.login__form, #username` | Login page detected |
| Feed loaded | `div.feed-shared-update-v2, main[role="main"]` | Feed is visible |
| Profile nav | `nav[aria-label="Primary"]` | Top navigation bar |
| CAPTCHA | `#captcha-internal` | Security challenge |

## Notification Detection

| Purpose | Selector | Notes |
|---------|----------|-------|
| Notifications page | `div.nt-card-list` | Notification container |
| Notification item | `div.nt-card` | Individual notification |
| Notification text | `div.nt-card__text` | Notification content |
| Notification time | `time.nt-card__time-ago` | Relative timestamp |
| Notification actor | `span.nt-card__actor` | Who triggered it |
| Unread indicator | `div.nt-card--unread` | Unread notification |
| Notification badge | `span.notification-badge__count` | Count in nav |

## Messaging Detection

| Purpose | Selector | Notes |
|---------|----------|-------|
| Messages page | `div.msg-conversations-container` | Messages list |
| Message thread | `div.msg-conversation-card` | Individual thread |
| Unread thread | `div.msg-conversation-card--unread` | Unread indicator |
| Thread name | `h3.msg-conversation-card__participant-names` | Sender name |
| Thread preview | `p.msg-conversation-card__message-snippet` | Message preview |
| Thread time | `time.msg-conversation-card__time-stamp` | Timestamp |

## Post Creation

| Purpose | Selector | Notes |
|---------|----------|-------|
| Start post button | `button.share-box-feed-entry__trigger` | "Start a post" |
| Start post alt | `button[aria-label*="Start a post"]` | Aria-based fallback |
| Post modal | `div.share-creation-state` | Post editor modal |
| Post text area | `div.ql-editor[data-placeholder]` | Rich text editor |
| Post text alt | `div[role="textbox"][contenteditable="true"]` | Contenteditable |
| Post button | `button.share-actions__primary-action` | "Post" submit button |
| Post button alt | `button[aria-label="Post"]` | Aria-based fallback |
| Post button alt2 | `button span:text("Post")` | Text-based fallback |
| Close modal | `button[aria-label="Dismiss"]` | Close post modal |

## Navigation

| Purpose | Selector | Notes |
|---------|----------|-------|
| Home/Feed | `a[href*="/feed/"]` | Navigate to feed |
| Notifications | `a[href*="/notifications/"]` | Navigate to notifications |
| Messaging | `a[href*="/messaging/"]` | Navigate to messages |
| Profile link | `a[href*="/in/"]` | Current user profile |

## Usage Patterns

### Check if logged in

```python
# If login form is visible, session is not active
login_form = page.query_selector('form.login__form, #username')
if login_form:
    # Need to log in
    pass

# If nav is visible, session is active
nav = page.query_selector('nav[aria-label="Primary"]')
if nav:
    # Logged in and ready
    pass
```

### Create a post

```python
# Click "Start a post"
start_btn = page.query_selector('button.share-box-feed-entry__trigger')
await start_btn.click()

# Wait for editor
editor = page.wait_for_selector('div[role="textbox"][contenteditable="true"]')

# Type content
await editor.fill(post_content)

# Click Post
post_btn = page.query_selector('button.share-actions__primary-action')
await post_btn.click()
```

## Selector Maintenance

When selectors break:

1. Open LinkedIn in a regular browser
2. Use DevTools (F12) to inspect elements
3. Look for `aria-label` and `role` attributes first (most stable)
4. Check for `data-*` attributes
5. Use class names as last resort (change frequently)
6. Update this file with new selectors and verification date
7. Test with `--once` flag before continuous monitoring
