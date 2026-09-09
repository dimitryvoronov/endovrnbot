"""Environment + paths. Loads .env once."""
import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
APP_ENV = os.getenv("APP_ENV", "dev")
IS_DEV = APP_ENV == "dev"

# Public https URL where the Mini App frontend is served (tunnel in dev).
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "diary.db")))
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", str(BASE_DIR / "data" / "media")))
FONT_DIR = BASE_DIR / "assets" / "fonts"

# initData older than this many seconds is rejected (0 disables the check).
INITDATA_TTL = int(os.getenv("INITDATA_TTL", "86400"))

# How the in-process bot receives updates: "polling" (outbound only, works from
# hosts Telegram cannot reach inbound) or "webhook".
BOT_MODE = os.getenv("BOT_MODE", "polling").strip().lower()

# Telegram user ids allowed to use the admin commands. The ADMIN_IDS env var
# (comma/space separated) replaces this default when set.
_DEFAULT_ADMIN_IDS = "216759030 1874185177"
ADMIN_IDS = {
    int(x)
    for x in os.getenv("ADMIN_IDS", _DEFAULT_ADMIN_IDS).replace(",", " ").split()
    if x.lstrip("-").isdigit()
}

# Secret for the Telegram webhook (header X-Telegram-Bot-Api-Secret-Token).
# Stable across restarts when derived from the token; override with an env var.
TG_WEBHOOK_SECRET = os.getenv("TG_WEBHOOK_SECRET") or (
    hashlib.sha256(f"wh:{BOT_TOKEN}".encode()).hexdigest()[:40] if BOT_TOKEN else ""
)

for _p in (DB_PATH.parent, MEDIA_DIR, FONT_DIR):
    _p.mkdir(parents=True, exist_ok=True)
