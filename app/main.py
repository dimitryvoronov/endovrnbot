"""Starlette backend: Mini App frontend + JSON API + PDF report, and the
Telegram bot (onboarding /start) served in-process via webhook.

Run:  uvicorn app.main:app --port 8000        (single worker)
"""
import contextlib
import json
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from telegram import Update as TgUpdate

from .auth import AuthError, user_from_request
from .bot import build_application, on_startup
from .config import (BASE_DIR, BOT_MODE, BOT_TOKEN, MEDIA_DIR,
                     TG_WEBHOOK_SECRET, WEBAPP_URL)
from .db import (init_db, insert_entry, list_entries, update_profile,
                 upsert_user)
from .report.aggregate import aggregate, alerts, window
from .report.pdf import build_report

WEB_DIR = BASE_DIR / "web"
init_db()

# Holds the running python-telegram-bot Application (webhook mode).
_bot = {}


@contextlib.asynccontextmanager
async def lifespan(_app):
    ptb = None
    if BOT_TOKEN:
        ptb = build_application(BOT_TOKEN)
        await ptb.initialize()
        await ptb.start()
        _bot["app"] = ptb
        with contextlib.suppress(Exception):
            await on_startup(ptb)

        if BOT_MODE == "webhook" and WEBAPP_URL and TG_WEBHOOK_SECRET:
            await ptb.bot.set_webhook(
                url=f"{WEBAPP_URL.rstrip('/')}/tg/webhook",
                secret_token=TG_WEBHOOK_SECRET,
                allowed_updates=TgUpdate.ALL_TYPES,
                drop_pending_updates=True,
            )
        else:  # polling: outbound only, works where Telegram can't reach us inbound
            with contextlib.suppress(Exception):
                await ptb.bot.delete_webhook(drop_pending_updates=True)
            await ptb.updater.start_polling(
                allowed_updates=TgUpdate.ALL_TYPES, drop_pending_updates=True
            )
    try:
        yield
    finally:
        if ptb:
            with contextlib.suppress(Exception):
                if ptb.updater and ptb.updater.running:
                    await ptb.updater.stop()
            with contextlib.suppress(Exception):
                await ptb.bot.delete_webhook()
            await ptb.stop()
            await ptb.shutdown()
            _bot.pop("app", None)


async def telegram_webhook(request):
    if request.headers.get("x-telegram-bot-api-secret-token") != TG_WEBHOOK_SECRET:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    ptb = _bot.get("app")
    if ptb is None:
        return JSONResponse({"detail": "bot not running"}, status_code=503)
    await ptb.process_update(TgUpdate.de_json(await request.json(), ptb.bot))
    return JSONResponse({"ok": True})


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def index(request):
    return FileResponse(WEB_DIR / "index.html")


async def me(request):
    u = user_from_request(request)
    return JSONResponse(dict(upsert_user(u.id, u.first_name)))


async def profile(request):
    u = user_from_request(request)
    upsert_user(u.id, u.first_name)
    update_profile(u.id, await request.json())
    return JSONResponse({"ok": True})


async def entries(request):
    u = user_from_request(request)
    upsert_user(u.id, u.first_name)

    if request.method == "GET":
        days = int(request.query_params.get("days", "30"))
        since, *_ = window(days)
        return JSONResponse([dict(r) for r in list_entries(u.id, since)])

    form = await request.form()
    data = json.loads(form["payload"])

    saved = []
    for up in form.getlist("photos")[:3]:
        ext = Path(getattr(up, "filename", "") or "").suffix.lower() or ".jpg"
        name = f"{uuid.uuid4().hex}{ext}"
        (MEDIA_DIR / name).write_bytes(await up.read())
        saved.append(name)

    eid = insert_entry(u.id, {
        "ts": data.get("ts") or _now_iso(),
        "meal_type": data.get("meal_type"),
        "hunger_before": data.get("hunger_before"),
        "satiety_after": data.get("satiety_after"),
        "company": data.get("company"),
        "distractions": data.get("distractions") or [],
        "emotion": data.get("emotion"),
        "photo_paths": saved,
        "note": data.get("note", ""),
    })
    return JSONResponse({"ok": True, "id": eid})


async def report(request):
    u = user_from_request(request)
    days = int((await request.json()).get("period_days", 7))
    urow = upsert_user(u.id, u.first_name)

    since, _until, now, start = window(days)
    rows = list_entries(u.id, since)
    agg = aggregate(rows)
    pdf = build_report(urow, rows, agg, alerts(agg, urow), days, now, start)

    fname = f"diary_report_{days}d_{urow['patient_code']}.pdf"
    sent, err = await _send_pdf(u.id, pdf, fname)
    return JSONResponse({"ok": True, "sent": sent, "error": err,
                         "entries": agg.get("count", 0)})


async def _send_pdf(chat_id: int, data: bytes, filename: str):
    if not BOT_TOKEN:
        return False, "BOT_TOKEN not set"
    caption = "Отчёт по дневнику питания"
    doc = BytesIO(data)
    try:
        ptb = _bot.get("app")
        if ptb is not None:
            await ptb.bot.send_document(chat_id=chat_id, document=doc,
                                        filename=filename, caption=caption)
        else:
            from telegram import Bot
            async with Bot(BOT_TOKEN) as bot:
                await bot.send_document(chat_id=chat_id, document=doc,
                                        filename=filename, caption=caption)
        return True, None
    except Exception as e:  # noqa: BLE001 - surface, don't 500 the report
        return False, f"{type(e).__name__}: {e}"


async def on_auth_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=401)


routes = [
    Route("/", index),
    Route("/api/me", me),
    Route("/api/profile", profile, methods=["POST"]),
    Route("/api/entries", entries, methods=["GET", "POST"]),
    Route("/api/report", report, methods=["POST"]),
    Route("/tg/webhook", telegram_webhook, methods=["POST"]),
    Mount("/static", app=StaticFiles(directory=str(WEB_DIR)), name="static"),
    Mount("/media", app=StaticFiles(directory=str(MEDIA_DIR)), name="media"),
]

app = Starlette(routes=routes, lifespan=lifespan,
                exception_handlers={AuthError: on_auth_error})
