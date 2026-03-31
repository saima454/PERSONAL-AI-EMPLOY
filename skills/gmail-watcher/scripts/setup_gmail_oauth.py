"""One-time OAuth2 setup script for Gmail API access.

Run this script to authenticate with Google and generate a token file
that the Gmail watcher uses for API access.

Usage:
    uv run python skills/gmail-watcher/scripts/setup_gmail_oauth.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def setup_oauth() -> None:
    """Run the OAuth2 consent flow and save the token."""
    load_dotenv()

    creds_path = Path(os.getenv("GMAIL_CREDENTIALS_PATH", "config/credentials.json"))
    token_path = Path(os.getenv("GMAIL_TOKEN_PATH", "config/token.json"))

    if not creds_path.exists():
        print(f"ERROR: Credentials file not found at {creds_path}")
        print()
        print("To get credentials:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project and enable the Gmail API")
        print("3. Go to APIs & Services > Credentials")
        print("4. Create OAuth 2.0 Client ID (Desktop app)")
        print("5. Download the JSON and save it as config/credentials.json")
        print()
        print("See skills/gmail-watcher/references/gmail_api_quickstart.md for details.")
        sys.exit(1)

    print("Starting OAuth2 flow...")
    print("A browser window will open for Google authentication.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")

    print()
    print(f"Token saved to {token_path}")
    print()
    print("Gmail watcher is ready. Run:")
    print("  uv run python backend/watchers/gmail_watcher.py --once    # Single check")
    print("  uv run python backend/watchers/gmail_watcher.py           # Continuous polling")


if __name__ == "__main__":
    setup_oauth()
