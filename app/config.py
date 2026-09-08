"""Environment + paths. Loads .env once."""
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

for _p in (DB_PATH.parent, MEDIA_DIR, FONT_DIR):
    _p.mkdir(parents=True, exist_ok=True)
