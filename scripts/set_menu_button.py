"""One-off: point the bot's chat menu button at the Mini App.

    python scripts/set_menu_button.py

Reads BOT_TOKEN and WEBAPP_URL from .env. Does not need the bot process running.
"""
import json
import sys
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

env = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
token = env.get("BOT_TOKEN")
url = env.get("WEBAPP_URL")

if not token or not url:
    sys.exit("Set BOT_TOKEN and WEBAPP_URL in .env first")

body = json.dumps({
    "menu_button": {"type": "web_app", "text": "Дневник", "web_app": {"url": url}}
}).encode()

req = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/setChatMenuButton",
    data=body, headers={"Content-Type": "application/json"},
)
print(urllib.request.urlopen(req).read().decode())
