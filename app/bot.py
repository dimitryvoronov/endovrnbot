"""Minimal bot: /start opens the Mini App, and the persistent menu button does too.

Run:  python -m app.bot
The backend (app.main) delivers the PDF via sendDocument; this process only needs
to run if you want /start to respond. Setting the menu button can also be done
one-off with scripts/set_menu_button.py.
"""
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp,
                      Update, WebAppInfo)
from telegram.ext import Application, CommandHandler, ContextTypes

# Works both as `python -m app.bot` and as a plain script `python app/bot.py`.
if __package__:
    from .config import BOT_TOKEN, WEBAPP_URL
else:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import BOT_TOKEN, WEBAPP_URL


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not WEBAPP_URL:
        await update.message.reply_text("WEBAPP_URL не задан в .env")
        return
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🍽 Открыть дневник", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await update.message.reply_text(
        "Дневник питания. Отмечайте приёмы пищи и собирайте PDF-отчёт для диетолога.",
        reply_markup=kb,
    )


async def _post_init(app: Application) -> None:
    if WEBAPP_URL:
        await app.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Дневник", web_app=WebAppInfo(url=WEBAPP_URL))
        )


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set in .env")
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
