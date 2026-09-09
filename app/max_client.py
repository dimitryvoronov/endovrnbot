"""Minimal async client for the MAX Bot API (https://botapi.max.ru).

Auth is the ?access_token= query param. Only the calls this bot needs.
"""
import asyncio

import httpx

from .config import BOT_TOKEN, MAX_API_BASE


class MaxError(RuntimeError):
    pass


class MaxClient:
    def __init__(self, token: str = BOT_TOKEN, base: str = MAX_API_BASE):
        self._token = token
        self._base = base.rstrip("/")
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(95.0, connect=10.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _req(self, method: str, path: str, *, params=None, json=None):
        params = dict(params or {})
        params["access_token"] = self._token
        r = await self._http.request(method, f"{self._base}{path}", params=params, json=json)
        if r.status_code >= 400:
            raise MaxError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    # --- bot ---
    async def get_me(self) -> dict:
        return await self._req("GET", "/me")

    # --- updates (long polling) ---
    async def get_updates(self, marker=None, timeout=30, types=None) -> dict:
        params = {"timeout": timeout, "limit": 100}
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        return await self._req("GET", "/updates", params=params)

    # --- webhook subscription ---
    async def subscribe(self, url: str, secret: str, types=None, version="0.0.1") -> dict:
        body = {"url": url, "secret": secret, "version": version}
        if types:
            body["update_types"] = list(types)
        return await self._req("POST", "/subscriptions", json=body)

    async def unsubscribe(self, url: str) -> dict:
        return await self._req("DELETE", "/subscriptions", params={"url": url})

    # --- messaging ---
    async def send_message(self, *, user_id=None, chat_id=None, text=None,
                           attachments=None, notify=True) -> dict:
        params = {}
        if user_id is not None:
            params["user_id"] = user_id
        if chat_id is not None:
            params["chat_id"] = chat_id
        body = {"text": text, "attachments": attachments or [], "notify": notify}
        return await self._req("POST", "/messages", params=params, json=body)

    async def answer_callback(self, callback_id: str, *, notification=None,
                              message=None) -> dict:
        body = {}
        if notification is not None:
            body["notification"] = notification
        if message is not None:
            body["message"] = message
        return await self._req("POST", "/answers", params={"callback_id": callback_id},
                               json=body)

    # --- file upload (3-step: get url -> POST binary -> attach token) ---
    async def send_document(self, *, user_id: int, data: bytes, filename: str,
                            caption: str = "") -> dict:
        up = await self._req("POST", "/uploads", params={"type": "file"})
        r = await self._http.post(up["url"], files={"data": (filename, data)})
        if r.status_code >= 400:
            raise MaxError(f"upload -> {r.status_code}: {r.text[:200]}")
        token_obj = r.json()  # {"token": "..."}
        attachment = {"type": "file", "payload": token_obj}
        last = None
        for _ in range(6):  # server may still be processing the file -> retry
            try:
                return await self.send_message(user_id=user_id, text=caption or None,
                                               attachments=[attachment])
            except MaxError as e:
                last = e
                await asyncio.sleep(1.5)
        raise last


# --- attachment / keyboard helpers ---

def inline_keyboard(rows: list[list[dict]]) -> dict:
    """rows: [[{"type": "callback", "text": "..", "payload": ".."}], ...]"""
    return {"type": "inline_keyboard", "payload": {"buttons": rows}}


def callback_btn(text: str, payload: str) -> dict:
    return {"type": "callback", "text": text, "payload": payload}


def open_app_btn(text: str, web_app_name: str) -> dict:
    return {"type": "open_app", "text": text, "web_app": web_app_name}
