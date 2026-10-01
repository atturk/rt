"""Read-only Telegram smoke check. Never prints the token or changes bot settings.

RT_MINI_TEST_TOKEN_FILE=/private/path/token python scripts/check_mini_app_bot.py
The file contains only a disposable test bot token, permissions 0600 recommended.
"""
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    filename = os.environ.get("RT_MINI_TEST_TOKEN_FILE")
    if not filename:
        print("Set RT_MINI_TEST_TOKEN_FILE to a private file containing the test bot token.")
        return 2
    token = Path(filename).read_text().strip()
    if not token or ":" not in token:
        print("Invalid token file format.")
        return 2
    def call(method):
        request = Request(f"https://api.telegram.org/bot{token}/{method}", data=b"", method="POST")
        with urlopen(request, timeout=10) as response:
            data = json.load(response)
        if not data.get("ok"):
            raise ValueError("Telegram rejected the check")
        return data["result"]
    try:
        bot = call("getMe")
        hook = call("getWebhookInfo")
    except HTTPError as exc:
        print(f"Telegram check failed: HTTP {exc.code}. No settings changed.")
        return 1
    except (URLError, TimeoutError, OSError, ValueError):
        print("Telegram check failed: network unavailable or invalid response. No settings changed.")
        return 1
    if not bot.get("is_bot"):
        print("Unexpected identity: not a bot.")
        return 1
    print(f"Bot identity verified: @{bot.get('username', '(unnamed)')}.")
    print("Webhook already configured." if hook.get("url") else "No webhook configured.")
    print("This does not verify Mini App launch, signed initData, microphone or audio delivery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
