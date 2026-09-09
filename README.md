# nutrition-diary-bot — MAX edition (`main-max`)

**MAX** ([max.ru](https://max.ru)) Mini App food-behaviour diary + PDF report for a
dietitian. Fork of the Telegram version on `main`; only the messenger layer differs
(`app/bot.py`, `app/max_client.py`, `web/` SDK). Shared modules — `db`, `report`,
`media`, `profile`, `auth` — are merged from `main`.

MAX Mini App launch data is signed with the same HMAC-SHA256 `WebAppData` scheme as
Telegram, so `app/auth.py` is unchanged and the frontend still sends
`Authorization: tma <initData>`.

Captured per meal: hunger before (0–4), photo(s), satiety after (0–4),
who you ate with, distractions, emotion, optional note.
`/api/report` aggregates a period and sends a PDF to the chat via the bot.

## Stack

| Part      | Choice |
|-----------|--------|
| Backend   | Starlette + uvicorn (`app/main.py`) |
| Frontend  | vanilla JS Mini App (`web/`) |
| Storage   | SQLite (`app/db.py`, `app/schema.sql`) + photos in `data/media/`, shrunk to JPEG on upload (`app/media.py`, `PHOTO_MAX_SIDE`/`PHOTO_QUALITY`) |
| PDF       | ReportLab (`app/report/pdf.py`) |
| Bot       | Hand-rolled MAX Bot API client (`app/max_client.py`) + dispatcher/FSM (`app/bot.py`). Runs **in the web process** (`app/main.py` lifespan) — polling (default) or webhook; `python -m app.bot` is standalone polling for local dev |

## Layout

```
app/
  main.py            Starlette API + static frontend + PDF delivery + /max/webhook
  bot.py             MaxBot: dispatcher + onboarding FSM + menu + /reset + admin
  max_client.py      async MAX Bot API client (updates, messages, callbacks, upload)
  profile.py         activity levels + Mifflin-St Jeor kcal estimate
  auth.py            initData (HMAC) validation — shared with Telegram build
  db.py schema.sql   sqlite layer
  report/
    aggregate.py     rows -> metrics (overeat / accumulated-hunger episodes, triggers)
    pdf.py           dietitian PDF (profile / aggregates / alerts / entries / photos)
web/                 index.html + app.js + style.css
scripts/
  fetch_fonts.py     DejaVu Sans -> assets/fonts/ (needed for Cyrillic in the PDF)
  set_menu_button.py one-off: menu button -> WEBAPP_URL
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/fetch_fonts.py            # Cyrillic font for the PDF
cp .env.example .env                     # then fill BOT_TOKEN (from MAX MasterBot)
```

Create the bot and get its `access_token` from **[@MasterBot](https://max.ru/MasterBot)**
in MAX. Register the Mini App URL and get the bot's public name in the MAX developer
console ([dev.max.ru](https://dev.max.ru)) — put that name in `MAX_WEBAPP_NAME` for
the in-chat "Открыть дневник" button.

## Run (dev)

1. **API**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   `APP_ENV=dev` lets you open <http://localhost:8000> in a plain browser — auth is
   bypassed with a fake user (`id=1`), so you can click through the form and
   `/api/entries`, `/api/report` (report `sent=false` until a tunnel + bot are set up).

2. **Expose over HTTPS** (Mini Apps require it):
   ```bash
   cloudflared tunnel --url http://localhost:8000     # or: ngrok http 8000
   ```
   Put the `https://…` URL into `.env` as `WEBAPP_URL`.

3. **Wire the bot:** the web process starts it automatically (polling). For a
   standalone loop: `python -m app.bot`. The Mini App URL and the menu/attach
   button are configured in the MAX developer console, not by this code.
   The report buttons live on the **История** tab; the PDF arrives as a file
   message from the bot.

## Deploy

Run `uvicorn app.main:app --host 0.0.0.0 --port <P>` (**single worker**) behind TLS
on any host. Set `APP_ENV=prod` and `WEBAPP_URL` to that origin. Keep the data dir
on a persistent volume.

The bot runs **inside this process** (Starlette lifespan). Update transport is
`BOT_MODE`:

- **`polling`** (default) — the app long-polls `GET /updates` (outbound only). Use
  this when MAX cannot open connections *to* your host.
- **`webhook`** — needs `WEBAPP_URL` reachable from MAX on port 80/443/8080/8443 or
  16384-32383; the app calls `POST /subscriptions` for `WEBAPP_URL/max/webhook`,
  verified by the `X-Max-Bot-Api-Secret` header (`MAX_WEBHOOK_SECRET`, or derived
  from the token).

Either way: do **not** also run `python -m app.bot` against the same token, and use
one uvicorn worker only (onboarding state is in-process memory).

### Amvera

`amvera.yml` is in the repo. Rules that matter:

- **`--host 0.0.0.0`** in the run command (default `127.0.0.1` → 503).
- Run command `--port` **must equal** `containerPort` (both `8000` here).
- No `--reload`.
- Env vars go in the Amvera panel (Переменные окружения), not a committed `.env`:
  `BOT_TOKEN` (MAX access_token), `APP_ENV=prod`,
  `WEBAPP_URL=https://<app>.amvera.io`, `MAX_WEBAPP_NAME=<bot public name>`,
  `ADMIN_IDS=<max ids>`, and `DB_PATH=/data/diary.db`, `MEDIA_DIR=/data/media`
  (mount a volume at `/data`, or data is wiped on redeploy).
- `singleton: true` — keep it one instance (in-process onboarding state).
- Fonts for the PDF are committed under `assets/fonts/`, so no build hook needed.

## Onboarding & menu

- `/start` (or the MAX **Start** button → `bot_started`) — if the profile is
  incomplete, runs a text conversation: name → sex (М/Ж) → age → height → weight →
  activity (1–5) → allergies → dislikes, saved to `users`. `/profile` re-runs it,
  `/cancel` aborts. Fills the report's "Профиль пациента" block (incl. Mifflin-St
  Jeor calorie estimate).
- `/menu` sends an inline keyboard: 「📝 Открыть дневник (open_app, needs
  `MAX_WEBAPP_NAME`) · 👤 Мой профиль · ❓ Помощь · 🗑 Сбросить профиль」.
  `👤 Мой профиль` shows the stored profile; `/reset` (or the button) wipes profile
  + entries + photos after an inline confirm.

## Admin commands

Restricted to MAX ids in `ADMIN_IDS` (env, comma/space separated). Silent for
everyone else.

- `/users` — registered users: code, pseudonym, sex/age, entry count, last entry
- `/userreport <P-00001|id> [days]` — build that user's dietitian PDF, sent to you
- `/userdiary <P-00001|id> [N]` — that user's last N entries as text

## Not done yet (deliberately)

- SCOFF (or any) eating-disorder screening and a gate on it.
- Consent flow / `/delete_me` / data-retention — **required before real users**
  (152-ФЗ: pseudonym, photos and self-reported states are personal data;
  health states are a special category).
- Reminders (the reference bot's 1/7/14/30-day follow-ups).
- Moving photos off local disk (S3/R2) and auth hardening for multi-tenant use.
