# Gmail API Setup Quickstart

Step-by-step guide to set up Gmail API access for the AI Employee Gmail Watcher.

## Prerequisites

- Google account with Gmail
- Python 3.13+ with `uv` package manager
- Project dependencies installed: `uv sync`

## Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** > **New Project**
3. Name it `AI Employee Gmail Watcher` (or any name)
4. Click **Create**

## Step 2: Enable the Gmail API

1. In the Cloud Console, go to **APIs & Services** > **Library**
2. Search for `Gmail API`
3. Click **Gmail API** > **Enable**

## Step 3: Configure OAuth Consent Screen

1. Go to **APIs & Services** > **OAuth consent screen**
2. Select **External** user type (or **Internal** for Google Workspace)
3. Fill in:
   - App name: `AI Employee Gmail Watcher`
   - User support email: your email
   - Developer contact email: your email
4. Click **Save and Continue**
5. On the **Scopes** page, click **Add or Remove Scopes**
6. Add these scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.modify`
7. Click **Save and Continue**
8. On the **Test users** page, add your Gmail address
9. Click **Save and Continue**

## Step 4: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **OAuth client ID**
3. Application type: **Desktop app**
4. Name: `AI Employee Desktop Client`
5. Click **Create**
6. Click **Download JSON** on the confirmation dialog
7. Save the file as `config/credentials.json` in the project root

## Step 5: Run the OAuth Setup Script

```bash
uv run python skills/gmail-watcher/scripts/setup_gmail_oauth.py
```

This will:
1. Open your browser for Google authentication
2. Ask you to sign in and grant permissions
3. Save the token to `config/token.json`

## Step 6: Verify the Setup

Run a single check to verify everything works:

```bash
uv run python backend/watchers/gmail_watcher.py --once
```

You should see log output indicating the watcher connected and checked for emails.

## Step 7: Configure .env

Copy the example and fill in your values:

```bash
cp config/.env.example .env
```

Key variables to set:

```bash
GMAIL_CREDENTIALS_PATH=config/credentials.json
GMAIL_TOKEN_PATH=config/token.json
GMAIL_CHECK_INTERVAL=120
DEV_MODE=true
DRY_RUN=true
```

## Running the Watcher

```bash
# Continuous polling (foreground)
uv run python backend/watchers/gmail_watcher.py

# Single check
uv run python backend/watchers/gmail_watcher.py --once

# Auth verification only
uv run python backend/watchers/gmail_watcher.py --auth-only
```

## Troubleshooting

### "Credentials file not found"

Ensure `config/credentials.json` exists. Re-download from Google Cloud Console if needed.

### "No valid Gmail token"

Run the OAuth setup script again:

```bash
uv run python skills/gmail-watcher/scripts/setup_gmail_oauth.py
```

### "Access denied" or "insufficient permissions"

1. Check that Gmail API is enabled in Cloud Console
2. Verify the OAuth scopes include `gmail.readonly` and `gmail.modify`
3. Ensure your email is listed as a test user in the OAuth consent screen

### "Token expired"

Tokens auto-refresh. If the refresh token itself expires (rare):

1. Delete `config/token.json`
2. Re-run `setup_gmail_oauth.py`

### "Quota exceeded"

Gmail API has daily quotas. If exceeded:

1. Increase `GMAIL_CHECK_INTERVAL` in `.env`
2. Wait for quota reset (resets daily)
3. Check [API quota dashboard](https://console.cloud.google.com/apis/api/gmail.googleapis.com/quotas)

## Security Notes

- `credentials.json` and `token.json` are in `.gitignore` and must never be committed
- The watcher uses read-only access by default (`mark_as_read: false`)
- `gmail.modify` scope is included for future mark-as-read capability but is not used by default
- All API calls are made locally; no data is sent to third parties
