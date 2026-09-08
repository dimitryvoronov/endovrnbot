"""Telegram Mini App initData validation.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
The frontend sends the raw initData string in `Authorization: tma <initData>`.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from .config import BOT_TOKEN, INITDATA_TTL, IS_DEV


class AuthError(Exception):
    pass


class TgUser:
    def __init__(self, id: int, first_name: str = "", username: str = "", raw: dict | None = None):
        self.id = id
        self.first_name = first_name
        self.username = username
        self.raw = raw or {}


def verify_init_data(init_data: str) -> dict:
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise AuthError("initData: no hash")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        raise AuthError("initData: bad signature")

    if INITDATA_TTL:
        auth_date = int(pairs.get("auth_date", "0"))
        if time.time() - auth_date > INITDATA_TTL:
            raise AuthError("initData: expired")
    return pairs


def user_from_request(request) -> TgUser:
    auth = request.headers.get("authorization", "")
    raw = auth[4:].strip() if auth.lower().startswith("tma ") else ""

    if not raw:
        if IS_DEV:
            return TgUser(id=1, first_name="Dev", username="dev")
        raise AuthError("missing Authorization: tma <initData>")

    pairs = verify_init_data(raw)
    u = json.loads(pairs.get("user", "{}"))
    if not u.get("id"):
        raise AuthError("initData: no user")
    return TgUser(
        id=int(u["id"]),
        first_name=u.get("first_name", ""),
        username=u.get("username", ""),
        raw=u,
    )
