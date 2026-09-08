"""Telegram bot: /start onboarding conversation that fills the patient profile.

`build_application()` is reused by the web process (webhook mode, app/main.py).
`main()` runs standalone long-polling for local dev:  python -m app.bot
"""
from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
                      KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
                      Update, WebAppInfo)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, ConversationHandler, MessageHandler,
                          filters)

if __package__:
    from .config import BOT_TOKEN, WEBAPP_URL
    from .db import delete_user, update_profile, upsert_user
    from .profile import ACTIVITY_CHOICES, SEX_CHOICES, bmi, estimate_kcal
else:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import BOT_TOKEN, WEBAPP_URL
    from app.db import delete_user, update_profile, upsert_user
    from app.profile import ACTIVITY_CHOICES, SEX_CHOICES, bmi, estimate_kcal

PSEUDONYM, SEX, AGE, HEIGHT, WEIGHT, ACTIVITY, ALLERGIES, DISLIKES = range(8)
_NO = {"нет", "-", "no", "не", "нету"}


HELP_TEXT = (
    "Что я умею:\n"
    "• 📝 Дневник — записывать приёмы пищи: голод до, фото, насыщение после, "
    "с кем и с чем ели, эмоции\n"
    "• 📊 Отчёт диетологу — PDF за 7/14/30 дней (внутри дневника, вкладка «История»)\n"
    "• 👤 Профиль — влияет на расчёты в отчёте (ИМТ, калораж)\n\n"
    "Команды:\n"
    "/profile — заполнить / изменить профиль\n"
    "/reset — удалить профиль и все записи\n"
    "/menu · /help · /start"
)

BOT_COMMANDS = [
    BotCommand("menu", "Меню"),
    BotCommand("profile", "Заполнить / изменить профиль"),
    BotCommand("reset", "Удалить профиль и записи"),
    BotCommand("help", "Что умеет бот"),
    BotCommand("start", "Начать"),
]


def _webapp_kb():
    if not WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🍽 Открыть дневник", web_app=WebAppInfo(url=WEBAPP_URL))]]
    )


def _menu_kb():
    """Persistent reply keyboard shown under the message box."""
    rows = [[KeyboardButton("👤 Мой профиль"), KeyboardButton("❓ Помощь")]]
    if WEBAPP_URL:
        rows.insert(0, [KeyboardButton("📝 Открыть дневник",
                                       web_app=WebAppInfo(url=WEBAPP_URL))])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def _profile_complete(u) -> bool:
    return bool(u and u["sex"] and u["age"] and u["height_cm"] and u["weight_kg"] and u["activity"])


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    u = upsert_user(tg.id, tg.first_name)
    if _profile_complete(u):
        await update.message.reply_text(
            f"С возвращением, {u['pseudonym'] or 'друг'}. "
            "Дневник и отчёт — по кнопкам ниже. Изменить профиль — /profile.",
            reply_markup=_menu_kb(),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "Здравствуйте! Я помогаю вести дневник питания и собирать отчёт для диетолога.\n\n"
        "Сначала пара вопросов о вас — это нужно для расчётов в отчёте. Прервать — /cancel.\n\n"
        "Как вас называть? Имя или псевдоним.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return PSEUDONYM


async def profile_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user.id, update.effective_user.first_name)
    await update.message.reply_text("Как вас называть? Имя или псевдоним.",
                                    reply_markup=ReplyKeyboardRemove())
    return PSEUDONYM


async def got_pseudonym(update, ctx):
    ctx.user_data["pseudonym"] = update.message.text.strip()[:64]
    await update.message.reply_text(
        "Ваш пол:",
        reply_markup=ReplyKeyboardMarkup([SEX_CHOICES], one_time_keyboard=True, resize_keyboard=True),
    )
    return SEX


async def got_sex(update, ctx):
    t = update.message.text.strip()
    if t not in SEX_CHOICES:
        await update.message.reply_text("Выберите кнопкой: " + " / ".join(SEX_CHOICES))
        return SEX
    ctx.user_data["sex"] = t
    await update.message.reply_text("Сколько вам лет? (число от 14 до 100)",
                                    reply_markup=ReplyKeyboardRemove())
    return AGE


async def got_age(update, ctx):
    try:
        age = int(update.message.text.strip())
        assert 14 <= age <= 100
    except (ValueError, AssertionError):
        await update.message.reply_text("Нужно число от 14 до 100.")
        return AGE
    ctx.user_data["age"] = age
    await update.message.reply_text("Ваш рост в см (число):")
    return HEIGHT


async def got_height(update, ctx):
    try:
        h = float(update.message.text.strip().replace(",", "."))
        assert 100 <= h <= 250
    except (ValueError, AssertionError):
        await update.message.reply_text("Нужно число в см, например 175.")
        return HEIGHT
    ctx.user_data["height_cm"] = h
    await update.message.reply_text("Ваш вес в кг (число, можно с дробью):")
    return WEIGHT


async def got_weight(update, ctx):
    try:
        w = float(update.message.text.strip().replace(",", "."))
        assert 30 <= w <= 400
    except (ValueError, AssertionError):
        await update.message.reply_text("Нужно число в кг, например 82.5.")
        return WEIGHT
    ctx.user_data["weight_kg"] = w
    await update.message.reply_text(
        "Уровень активности:",
        reply_markup=ReplyKeyboardMarkup([[c] for c in ACTIVITY_CHOICES],
                                         one_time_keyboard=True, resize_keyboard=True),
    )
    return ACTIVITY


async def got_activity(update, ctx):
    t = update.message.text.strip()
    if t not in ACTIVITY_CHOICES:
        await update.message.reply_text("Выберите кнопкой из списка.")
        return ACTIVITY
    ctx.user_data["activity"] = t
    await update.message.reply_text(
        "Пищевые аллергии? Перечислите через запятую или напишите «нет».",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ALLERGIES


async def got_allergies(update, ctx):
    t = update.message.text.strip()
    ctx.user_data["allergies"] = "" if t.lower() in _NO else t[:255]
    await update.message.reply_text("Продукты, которые вы не любите? Через запятую или «нет».")
    return DISLIKES


async def got_dislikes(update, ctx):
    d = ctx.user_data
    t = update.message.text.strip()
    d["dislikes"] = "" if t.lower() in _NO else t[:255]

    update_profile(update.effective_user.id, {
        "pseudonym": d.get("pseudonym"),
        "sex": d.get("sex"), "age": d.get("age"),
        "height_cm": d.get("height_cm"), "weight_kg": d.get("weight_kg"),
        "activity": d.get("activity"),
        "allergies": d.get("allergies", ""), "dislikes": d.get("dislikes", ""),
    })
    kcal = estimate_kcal(d.get("sex"), d.get("age"), d.get("height_cm"),
                         d.get("weight_kg"), d.get("activity"))
    await update.message.reply_text(
        "Профиль сохранён:\n"
        f"• {d.get('pseudonym')}, {str(d.get('sex', '')).lower()}, {d.get('age')} лет\n"
        f"• рост {d.get('height_cm')} см, вес {d.get('weight_kg')} кг, "
        f"ИМТ {bmi(d.get('height_cm'), d.get('weight_kg'))}\n"
        f"• активность: {d.get('activity')}\n"
        f"• расчётный калораж: {kcal} ккал/сутки\n\n"
        "Это ориентир для отчёта, не назначение диетолога. Теперь можно вести дневник.",
        reply_markup=_menu_kb(),
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def cancel(update, ctx):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено. Начать заново — /profile.",
                                    reply_markup=_menu_kb())
    return ConversationHandler.END


async def menu_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Меню:", reply_markup=_menu_kb())


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, reply_markup=_menu_kb())


async def show_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = upsert_user(update.effective_user.id, update.effective_user.first_name)
    if not _profile_complete(u):
        await update.message.reply_text(
            "Профиль ещё не заполнен. Заполнить — /profile.", reply_markup=_menu_kb()
        )
        return
    kcal = estimate_kcal(u["sex"], u["age"], u["height_cm"], u["weight_kg"], u["activity"])
    await update.message.reply_text(
        "Ваш профиль:\n"
        f"• {u['pseudonym']}, {str(u['sex']).lower()}, {u['age']} лет\n"
        f"• рост {u['height_cm']} см, вес {u['weight_kg']} кг, "
        f"ИМТ {bmi(u['height_cm'], u['weight_kg'])}\n"
        f"• активность: {u['activity']}\n"
        f"• аллергии: {u['allergies'] or '—'}\n"
        f"• не любит: {u['dislikes'] or '—'}\n"
        f"• расчётный калораж: {kcal} ккал/сутки\n\n"
        "Изменить — /profile · удалить — /reset",
        reply_markup=_menu_kb(),
    )


async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑 Удалить всё", callback_data="reset:yes"),
        InlineKeyboardButton("Отмена", callback_data="reset:no"),
    ]])
    await update.message.reply_text(
        "Удалить профиль и все записи дневника? Отменить нельзя.", reply_markup=kb
    )


async def reset_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "reset:yes":
        delete_user(q.from_user.id)
        await q.edit_message_text("Профиль и записи удалены. /start — заполнить заново.")
    else:
        await q.edit_message_text("Отменено.")


def build_application(token: str, post_init=None) -> Application:
    builder = Application.builder().token(token)
    if post_init is not None:
        builder = builder.post_init(post_init)
    app = builder.build()
    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("profile", profile_cmd),
        ],
        states={
            PSEUDONYM: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_pseudonym)],
            SEX: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_sex)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_age)],
            HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_height)],
            WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_weight)],
            ACTIVITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_activity)],
            ALLERGIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_allergies)],
            DISLIKES: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_dislikes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="onboarding",
    ))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CallbackQueryHandler(reset_cb, pattern=r"^reset:"))
    app.add_handler(MessageHandler(filters.Regex(r"^❓ Помощь$"), help_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"^👤 Мой профиль$"), show_profile))
    return app


async def on_startup(app: Application) -> None:
    # Only the command list is managed here. The chat menu button is left for
    # you to configure in BotFather (Bot Settings -> Menu Button).
    await app.bot.set_my_commands(BOT_COMMANDS)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set in .env")
    app = build_application(BOT_TOKEN, post_init=on_startup)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
