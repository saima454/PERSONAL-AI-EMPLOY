# Gmail Watcher Configuration Schema

This document defines the configuration options for the gmail-watcher.

## Configuration File

Location: `config/gmail_config.json`

## Full Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",

  "query": {
    "type": "string",
    "description": "Gmail search query for filtering emails",
    "default": "is:unread (is:important OR subject:(urgent OR invoice OR payment OR asap OR help))"
  },

  "priority_keywords": {
    "type": "object",
    "description": "Keywords that determine email priority",
    "properties": {
      "high": {
        "type": "array",
        "items": { "type": "string" },
        "default": ["urgent", "asap", "immediate", "critical", "payment", "invoice"]
      },
      "medium": {
        "type": "array",
        "items": { "type": "string" },
        "default": ["important", "request", "review", "deadline"]
      },
      "low": {
        "type": "array",
        "items": { "type": "string" },
        "default": []
      }
    }
  },

  "exclude_senders": {
    "type": "array",
    "description": "Email patterns to exclude (partial match)",
    "items": { "type": "string" },
    "default": ["noreply@", "newsletter@", "notifications@", "no-reply@"]
  },

  "include_senders": {
    "type": "array",
    "description": "If set, ONLY process emails from these senders",
    "items": { "type": "string" },
    "default": []
  },

  "max_results": {
    "type": "integer",
    "description": "Maximum emails to fetch per poll",
    "minimum": 1,
    "maximum": 100,
    "default": 10
  },

  "poll_interval_seconds": {
    "type": "integer",
    "description": "Seconds between Gmail API polls",
    "minimum": 60,
    "maximum": 3600,
    "default": 120
  },

  "processed_ids_retention_days": {
    "type": "integer",
    "description": "Days to keep processed email IDs",
    "minimum": 1,
    "maximum": 365,
    "default": 30
  },

  "mark_as_read": {
    "type": "boolean",
    "description": "Whether to mark processed emails as read in Gmail",
    "default": false
  },

  "include_attachments": {
    "type": "boolean",
    "description": "Whether to note attachment info in action files",
    "default": true
  },

  "snippet_max_length": {
    "type": "integer",
    "description": "Maximum characters for email snippet in action file",
    "minimum": 100,
    "maximum": 5000,
    "default": 1000
  }
}
```

## Default Configuration

```json
{
  "query": "is:unread (is:important OR subject:(urgent OR invoice OR payment OR asap OR help))",
  "priority_keywords": {
    "high": ["urgent", "asap", "immediate", "critical", "payment", "invoice"],
    "medium": ["important", "request", "review", "deadline"],
    "low": []
  },
  "exclude_senders": [
    "noreply@",
    "newsletter@",
    "notifications@",
    "no-reply@",
    "mailer-daemon@"
  ],
  "include_senders": [],
  "max_results": 10,
  "poll_interval_seconds": 120,
  "processed_ids_retention_days": 30,
  "mark_as_read": false,
  "include_attachments": true,
  "snippet_max_length": 1000
}
```

## Example: VIP-Only Configuration

Only process emails from specific senders:

```json
{
  "query": "is:unread",
  "include_senders": [
    "ceo@company.com",
    "client@bigclient.com",
    "support@vendor.com"
  ],
  "priority_keywords": {
    "high": ["urgent", "asap"],
    "medium": [],
    "low": []
  },
  "max_results": 20,
  "poll_interval_seconds": 60
}
```

## Example: Business Hours Only

Combined with a cron job that only runs the watcher during business hours:

```json
{
  "query": "is:unread is:important",
  "max_results": 50,
  "poll_interval_seconds": 300,
  "mark_as_read": false
}
```

## Environment Variable Overrides

These environment variables override config file settings:

| Variable | Config Key | Type |
|----------|------------|------|
| `GMAIL_POLL_INTERVAL_SECONDS` | `poll_interval_seconds` | int |
| `GMAIL_MAX_RESULTS` | `max_results` | int |
| `GMAIL_QUERY` | `query` | string |

Environment variables take precedence over config file.
