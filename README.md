# nutrition-diary-bot

Telegram **Mini App** food-behaviour diary + PDF report for a dietitian.
A trimmed re-implementation of the `@KF_NUTRITION_BOT` diary flow.

Captured per meal: hunger before (0–4), photo(s), satiety after (0–4),
who you ate with, distractions, emotion, optional note.
`/api/report` aggregates a period and sends a PDF to the chat via the bot.

## Stack

| Part      | Choice |
|-----------|--------|
| Backend   | Starlette + uvicorn (`app/main.py`) |
| Frontend  | vanilla JS Mini App (`web/`) |
| Storage   | SQLite (`app/db.py`, `app/schema.sql`) + files in `data/media/` |
| PDF       | ReportLab (`app/report/pdf.py`) |
| Bot       | python-telegram-bot; `/start` onboarding conversation. In prod it runs **in the web process via webhook** (`app/main.py` lifespan); `python -m app.bot` is long-polling for local dev |

## Layout

```
app/
  main.py            Starlette API + static frontend + PDF delivery + /tg/webhook
  bot.py             /start & /profile onboarding conversation; build_application()
  profile.py         activity levels + Mifflin-St Jeor kcal estimate
  auth.py            initData (HMAC) validation
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
cp .env.example .env                     # then fill BOT_TOKEN (from @BotFather)
```

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

3. **Wire the bot:**
   ```bash
   python scripts/set_menu_button.py     # menu button -> Mini App
   python -m app.bot                     # optional: makes /start reply too
   ```
   Open the bot in Telegram → menu button (or `/start`) → the Mini App opens.
   `Сохранить запись` is the Telegram MainButton; the report buttons live on the
   **История** tab and the PDF arrives as a message from the bot.

## Deploy

Run `uvicorn app.main:app --host 0.0.0.0 --port <P>` (**single worker**) behind TLS
on any host (Fly.io / Render / a VPS with Caddy). Set `APP_ENV=prod` and
`WEBAPP_URL` to that origin. Keep the data dir on a persistent volume.

The bot runs **inside this process**: on startup the lifespan builds the PTB
`Application`, registers a Telegram webhook at `WEBAPP_URL/tg/webhook` (verified by
the `X-Telegram-Bot-Api-Secret-Token` header, secret from `TG_WEBHOOK_SECRET` or
derived from the token), and sets the menu button + command list. So:

- `WEBAPP_URL` **must** be set in prod or the bot gets no updates.
- Do **not** also run `python -m app.bot` against the same token — polling and
  webhook are mutually exclusive.
- One uvicorn worker only (conversation state is in-process memory).

### Amvera

`amvera.yml` is in the repo. Rules that matter:

- **`--host 0.0.0.0`** in the run command (default `127.0.0.1` → 503).
- Run command `--port` **must equal** `containerPort` (both `8000` here).
- No `--reload`.
- Env vars go in the Amvera panel (Переменные окружения), not a committed `.env`:
  `BOT_TOKEN`, `APP_ENV=prod`, `WEBAPP_URL=https://<app>.amvera.io` (required —
  the bot webhook needs it), and `DB_PATH=/data/diary.db`, `MEDIA_DIR=/data/media`
  (mount a volume at `/data`, or data is wiped on redeploy).
- `singleton: true` — keep it one instance (in-process conversation state).
- Fonts for the PDF are committed under `assets/fonts/`, so no build hook needed.

## Onboarding & menu

- `/start` — if the profile is incomplete, runs a conversation: name → sex → age →
  height → weight → activity → allergies → dislikes, saved to `users`. `/profile`
  re-runs it, `/cancel` aborts. The report's "Профиль пациента" block (incl.
  Mifflin-St Jeor calorie estimate) is filled from this.
- The Telegram **menu button** is a single button (opens the Mini App). Multiple
  choices come from the **command list** (`/menu /profile /help /start`, set via
  `setMyCommands`) and a **persistent reply keyboard** (`/menu`) with
  「📝 Открыть дневник · 👤 Мой профиль · ❓ Помощь」.

## Not done yet (deliberately)

- SCOFF (or any) eating-disorder screening and a gate on it.
- Consent flow / `/delete_me` / data-retention — **required before real users**
  (152-ФЗ: pseudonym, photos and self-reported states are personal data;
  health states are a special category).
- Reminders (the reference bot's 1/7/14/30-day follow-ups).
- Moving photos off local disk (S3/R2) and auth hardening for multi-tenant use.
