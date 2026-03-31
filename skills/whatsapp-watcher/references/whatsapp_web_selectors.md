# WhatsApp Web Selectors Reference

WhatsApp Web uses dynamically generated class names that change with updates.
This file documents the structural selectors used by the watcher. These should
be verified and updated when WhatsApp Web pushes UI changes.

**Last verified:** 2026-02-11

## Important Note

WhatsApp Web's DOM structure changes frequently. The selectors below use
`aria-label` attributes and structural patterns that are more stable than
class names. Always test selectors before relying on them in production.

## Core Selectors

### Session State Detection

| Purpose | Selector | Notes |
|---------|----------|-------|
| QR code canvas | `canvas[aria-label="Scan this QR code to link a device!"]` | Indicates need to scan QR |
| QR code fallback | `div[data-testid="qrcode"]` | Alternative QR detection |
| Phone disconnected | `div[data-testid="alert-phone"]` | "Phone not connected" banner |
| Loading spinner | `div[data-testid="startup"]` | App is loading |
| Chat list loaded | `div[data-testid="chat-list"]` | Main interface ready |

### Unread Chat Detection

| Purpose | Selector | Notes |
|---------|----------|-------|
| Chat list container | `div[aria-label="Chat list"]` | Parent container for all chats |
| Individual chat row | `div[data-testid="cell-frame-container"]` | Each chat entry |
| Individual chat row (alt) | `div[role="listitem"]` | Alternative row selector |
| Unread badge | `span[data-testid="icon-unread-count"]` | Unread message count badge |
| Unread count text | `span[aria-label*="unread"]` | Contains count as text |
| Side pane | `#pane-side` | Left panel with all chats |
| Chat name in pane | `#pane-side span[title]` | Chat names via title attribute |

### Chat Content Extraction

| Purpose | Selector | Notes |
|---------|----------|-------|
| Chat header name | `div[data-testid="conversation-header"] span[dir="auto"]` | Contact/group name |
| Chat header (alt) | `header span[dir="auto"]` | Alternative header selector |
| Conversation panel | `div[data-testid="conversation-panel-wrapper"]` | Indicates chat is open |
| Message container | `div[data-testid="msg-container"]` | Individual message bubble |
| Message container (alt) | `div.message-in` | Incoming message class-based |
| Message text | `span[data-testid="msg-text"] span` | Text content of message |
| Message text (alt) | `span.selectable-text span` | Class-based text selector |
| Message text (alt2) | `span[dir="ltr"]` | Direction-based text selector |
| Message timestamp | `div[data-testid="msg-meta"] span` | Time shown on message |
| Message timestamp (alt) | `span[data-testid="msg-time"]` | Alternative time selector |
| Message metadata | `div[data-pre-plain-text]` | Contains sender/time in attribute |
| Sender name (group) | `span[data-testid="msg-author"]` | Only in group chats |

### Navigation

| Purpose | Selector | Notes |
|---------|----------|-------|
| Search box | `div[data-testid="chat-list-search"]` | Search input |
| Back button | `button[data-testid="back"]` | Navigate back from chat |
| Chat title click | `div[data-testid="conversation-header"]` | Opens chat info |

## Usage Patterns

### Check if logged in

```python
# If QR code is visible, session is not active
qr = page.query_selector('canvas[aria-label*="Scan this QR code"]')
if qr:
    # Need to scan QR code
    pass

# If chat list is visible, session is active
chat_list = page.query_selector('div[data-testid="chat-list"]')
if chat_list:
    # Ready to monitor
    pass
```

### Find unread chats

```python
# Get all chat rows with unread badges
unread_chats = page.query_selector_all(
    'div[data-testid="cell-frame-container"]:has(span[data-testid="icon-unread-count"])'
)
```

### Extract messages from a chat

```python
# Click on a chat to open it, then:
messages = page.query_selector_all('div[data-testid="msg-container"]')
for msg in messages:
    text_el = msg.query_selector('span[data-testid="msg-text"] span')
    time_el = msg.query_selector('div[data-testid="msg-meta"] span')
    text = text_el.inner_text() if text_el else ""
    time = time_el.inner_text() if time_el else ""
```

## Selector Maintenance

When selectors break (elements not found):

1. Open WhatsApp Web in a regular browser
2. Use DevTools (F12) to inspect elements
3. Look for `data-testid` attributes first (most stable)
4. Fall back to `aria-label` attributes
5. Use structural selectors (tag hierarchy) as last resort
6. Update this file with new selectors and verification date
7. Test with `--once` flag before running continuous monitoring
