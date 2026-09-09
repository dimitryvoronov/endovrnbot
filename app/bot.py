"""MAX bot: /start onboarding conversation that fills the patient profile,
menu, /reset, and admin commands. Hand-rolled dispatcher over the MAX Bot API
(no framework). Onboarding state is in-process memory, keyed by user id.

`MaxBot` is driven by the web process (app/main.py) via webhook or a polling task.
`python -m app.bot` runs standalone long-polling for local dev.
"""
import asyncio
import contextlib
import json
import logging

from .config import ADMIN_IDS, BOT_TOKEN, MAX_WEBAPP_NAME
from .db import (delete_user, list_entries, list_users_summary, recent_entries,
                 resolve_user, update_profile, upsert_user)
from .max_client import MaxClient, callback_btn, inline_keyboard, open_app_btn
from .profile import ACTIVITY_CHOICES, bmi, estimate_kcal
from .report.aggregate import aggregate, alerts, window
from .report.pdf import build_report

log = logging.getLogger("maxbot")

STEPS = ["pseudonym", "sex", "age", "height", "weight", "activity", "allergies", "dislikes"]
_NO = {"нет", "-", "no", "не", "нету"}
_SEX = {"м": "Мужской", "муж": "Мужской", "мужской": "Мужской",
        "ж": "Женский", "жен": "Женский", "женский": "Женский"}

HELP_TEXT = (
    "Что я умею:\n"
    "• 📝 Дневник — записывать приёмы пищи: голод до, фото, насыщение после, "
    "с кем и с чем ели, эмоции\n"
    "• 📊 Отчёт диетологу — PDF за 7/14/30 дней (внутри дневника, вкладка «История»)\n"
    "• 👤 Профиль — влияет на расчёты в отчёте (ИМТ, калораж)\n\n"
    "Команды: /profile · /reset · /menu · /help"
)


def _activity_list() -> str:
    return "\n".join(f"{i}. {name}" for i, name in enumerate(ACTIVITY_CHOICES, 1))


class MaxBot:
    def __init__(self, client: MaxClient | None = None):
        self.client = client or MaxClient()
        self._fsm: dict[int, dict] = {}          # user_id -> {"step": str, "data": {}}
        self._poll_task: asyncio.Task | None = None
        self._marker = None

    async def aclose(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
        await self.client.aclose()

    # ------------------------------------------------------------------ menus
    def _menu_kb(self):
        rows = []
        if MAX_WEBAPP_NAME:
            rows.append([open_app_btn("📝 Открыть дневник", MAX_WEBAPP_NAME)])
        rows.append([callback_btn("👤 Мой профиль", "menu:profile"),
                     callback_btn("❓ Помощь", "menu:help")])
        rows.append([callback_btn("🗑 Сбросить профиль", "menu:reset")])
        return inline_keyboard(rows)

    async def _send(self, user_id: int, text: str, keyboard=None) -> None:
        atts = [keyboard] if keyboard else []
        await self.client.send_message(user_id=user_id, text=text, attachments=atts)

    # ------------------------------------------------------------------ dispatch
    async def handle(self, update: dict) -> None:
        t = update.get("update_type")
        try:
            if t == "bot_started":
                await self._on_start(update["user"]["user_id"])
            elif t == "message_created":
                msg = update["message"]
                uid = msg["sender"]["user_id"]
                text = (msg.get("body") or {}).get("text") or ""
                await self._on_text(uid, text.strip())
            elif t == "message_callback":
                cb = update["callback"]
                await self._on_callback(cb["user"]["user_id"], cb["callback_id"],
                                        cb.get("payload") or "")
        except Exception:  # noqa: BLE001 - never let one update kill the loop
            log.exception("handling update failed: %s", t)

    # ------------------------------------------------------------------ handlers
    async def _on_start(self, uid: int) -> None:
        self._fsm.pop(uid, None)
        u = upsert_user(uid, "")
        if _profile_complete(u):
            await self._send(uid, f"С возвращением, {u['pseudonym'] or 'друг'}. "
                                  "Дневник и отчёт — по кнопкам ниже. Профиль — /profile.",
                             self._menu_kb())
            return
        self._fsm[uid] = {"step": "pseudonym", "data": {}}
        await self._send(uid,
                         "Здравствуйте! Я помогаю вести дневник питания и собирать отчёт "
                         "для диетолога.\n\nСначала пара вопросов о вас — это нужно для "
                         "расчётов в отчёте. Прервать — /cancel.\n\n"
                         "Как вас называть? Имя или псевдоним.")

    async def _on_text(self, uid: int, text: str) -> None:
        if text.startswith("/"):
            return await self._on_command(uid, text)
        st = self._fsm.get(uid)
        if st:
            return await self._on_answer(uid, st, text)
        # not in a flow, not a command
        await self._send(uid, "Не понял. /menu — меню, /help — что я умею.")

    async def _on_command(self, uid: int, text: str) -> None:
        cmd, _, arg = text[1:].partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        if cmd in ("start", "profile"):
            if cmd == "profile":
                self._fsm[uid] = {"step": "pseudonym", "data": {}}
                upsert_user(uid, "")
                await self._send(uid, "Как вас называть? Имя или псевдоним.")
            else:
                await self._on_start(uid)
        elif cmd == "cancel":
            self._fsm.pop(uid, None)
            await self._send(uid, "Отменено. Начать заново — /profile.", self._menu_kb())
        elif cmd == "menu":
            await self._send(uid, "Меню:", self._menu_kb())
        elif cmd == "help":
            await self._send(uid, HELP_TEXT, self._menu_kb())
        elif cmd == "reset":
            await self._reset_prompt(uid)
        elif cmd == "whoami":
            await self._send(uid, f"Ваш MAX ID: {uid}")
        elif cmd == "users":
            await self._admin_users(uid)
        elif cmd == "userreport":
            await self._admin_userreport(uid, arg)
        elif cmd == "userdiary":
            await self._admin_userdiary(uid, arg)
        else:
            await self._send(uid, "Неизвестная команда. /help")

    async def _on_answer(self, uid: int, st: dict, text: str) -> None:
        step, data = st["step"], st["data"]

        if step == "pseudonym":
            data["pseudonym"] = text[:64]
            st["step"] = "sex"
            return await self._send(uid, "Ваш пол? Напишите: М или Ж")
        if step == "sex":
            v = _SEX.get(text.lower())
            if not v:
                return await self._send(uid, "Напишите М или Ж.")
            data["sex"] = v
            st["step"] = "age"
            return await self._send(uid, "Сколько вам лет? (число от 14 до 100)")
        if step == "age":
            if not (text.isdigit() and 14 <= int(text) <= 100):
                return await self._send(uid, "Нужно число от 14 до 100.")
            data["age"] = int(text)
            st["step"] = "height"
            return await self._send(uid, "Ваш рост в см (число):")
        if step == "height":
            h = _num(text)
            if h is None or not (100 <= h <= 250):
                return await self._send(uid, "Нужно число в см, например 175.")
            data["height_cm"] = h
            st["step"] = "weight"
            return await self._send(uid, "Ваш вес в кг (число, можно с дробью):")
        if step == "weight":
            w = _num(text)
            if w is None or not (30 <= w <= 400):
                return await self._send(uid, "Нужно число в кг, например 82.5.")
            data["weight_kg"] = w
            st["step"] = "activity"
            return await self._send(uid, "Уровень активности — напишите номер:\n" + _activity_list())
        if step == "activity":
            if not (text.isdigit() and 1 <= int(text) <= len(ACTIVITY_CHOICES)):
                return await self._send(uid, "Напишите номер от 1 до "
                                        f"{len(ACTIVITY_CHOICES)}.")
            data["activity"] = ACTIVITY_CHOICES[int(text) - 1]
            st["step"] = "allergies"
            return await self._send(uid, "Пищевые аллергии? Перечислите через запятую "
                                    "или напишите «нет».")
        if step == "allergies":
            data["allergies"] = "" if text.lower() in _NO else text[:255]
            st["step"] = "dislikes"
            return await self._send(uid, "Продукты, которые вы не любите? Через запятую или «нет».")
        if step == "dislikes":
            data["dislikes"] = "" if text.lower() in _NO else text[:255]
            self._fsm.pop(uid, None)
            update_profile(uid, data)
            kcal = estimate_kcal(data["sex"], data["age"], data["height_cm"],
                                 data["weight_kg"], data["activity"])
            await self._send(
                uid,
                "Профиль сохранён:\n"
                f"• {data['pseudonym']}, {data['sex'].lower()}, {data['age']} лет\n"
                f"• рост {data['height_cm']} см, вес {data['weight_kg']} кг, "
                f"ИМТ {bmi(data['height_cm'], data['weight_kg'])}\n"
                f"• активность: {data['activity']}\n"
                f"• расчётный калораж: {kcal} ккал/сутки\n\n"
                "Это ориентир для отчёта, не назначение диетолога. Теперь можно вести дневник.",
                self._menu_kb(),
            )

    async def _on_callback(self, uid: int, callback_id: str, payload: str) -> None:
        with contextlib.suppress(Exception):
            await self.client.answer_callback(callback_id)
        if payload == "menu:profile":
            await self._show_profile(uid)
        elif payload == "menu:help":
            await self._send(uid, HELP_TEXT, self._menu_kb())
        elif payload == "menu:reset":
            await self._reset_prompt(uid)
        elif payload == "reset:yes":
            delete_user(uid)
            self._fsm.pop(uid, None)
            await self._send(uid, "Профиль и записи удалены. /start — заполнить заново.")
        elif payload == "reset:no":
            await self._send(uid, "Отменено.")

    # ------------------------------------------------------------------ profile view
    async def _show_profile(self, uid: int) -> None:
        u = upsert_user(uid, "")
        if not _profile_complete(u):
            return await self._send(uid, "Профиль ещё не заполнен. Заполнить — /profile.",
                                    self._menu_kb())
        kcal = estimate_kcal(u["sex"], u["age"], u["height_cm"], u["weight_kg"], u["activity"])
        await self._send(
            uid,
            "Ваш профиль:\n"
            f"• {u['pseudonym']}, {str(u['sex']).lower()}, {u['age']} лет\n"
            f"• рост {u['height_cm']} см, вес {u['weight_kg']} кг, "
            f"ИМТ {bmi(u['height_cm'], u['weight_kg'])}\n"
            f"• активность: {u['activity']}\n"
            f"• аллергии: {u['allergies'] or '—'}\n"
            f"• не любит: {u['dislikes'] or '—'}\n"
            f"• расчётный калораж: {kcal} ккал/сутки\n\n"
            "Изменить — /profile · удалить — /reset",
            self._menu_kb(),
        )

    async def _reset_prompt(self, uid: int) -> None:
        kb = inline_keyboard([[callback_btn("🗑 Удалить всё", "reset:yes"),
                               callback_btn("Отмена", "reset:no")]])
        await self._send(uid, "Удалить профиль и все записи дневника? Отменить нельзя.", kb)

    # ------------------------------------------------------------------ admin
    def _is_admin(self, uid: int) -> bool:
        return uid in ADMIN_IDS

    async def _admin_users(self, uid: int) -> None:
        if not self._is_admin(uid):
            return
        rows = list_users_summary()
        if not rows:
            return await self._send(uid, "Пользователей нет.")
        out = ["Пользователи:"]
        for r in rows:
            last = (r["last_entry"] or "—")[:16].replace("T", " ")
            out.append(f"{r['patient_code']} · {r['pseudonym'] or '—'} · "
                       f"{r['sex'] or '—'}/{r['age'] or '—'} · записей {r['n_entries']} · посл. {last}")
        out.append("\n/userreport <код|id> [дней] · /userdiary <код|id> [N]")
        await self._send(uid, "\n".join(out))

    async def _admin_userreport(self, uid: int, arg: str) -> None:
        if not self._is_admin(uid):
            return
        parts = arg.split()
        if not parts:
            return await self._send(uid, "Использование: /userreport <P-00001|id> [дней]")
        u = resolve_user(parts[0])
        if not u:
            return await self._send(uid, "Пользователь не найден.")
        days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 7
        since, _until, now, start = window(days)
        rows = list_entries(u["tg_user_id"], since)
        agg = aggregate(rows)
        pdf = build_report(u, rows, agg, alerts(agg, u), days, now, start)
        await self.client.send_document(
            user_id=uid, data=pdf,
            filename=f"diary_report_{days}d_{u['patient_code']}.pdf",
            caption=f"{u['patient_code']} · {u['pseudonym'] or '—'} · {days} дн.",
        )

    async def _admin_userdiary(self, uid: int, arg: str) -> None:
        if not self._is_admin(uid):
            return
        parts = arg.split()
        if not parts:
            return await self._send(uid, "Использование: /userdiary <P-00001|id> [N]")
        u = resolve_user(parts[0])
        if not u:
            return await self._send(uid, "Пользователь не найден.")
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
        rows = recent_entries(u["tg_user_id"], n)
        if not rows:
            return await self._send(uid, "Записей нет.")
        out = [f"{u['patient_code']} · {u['pseudonym'] or '—'} — последние {len(rows)}:"]
        for r in rows:
            dz = ", ".join(_loads(r["distractions"]))
            extra = "".join([f" · {dz}" if dz else "",
                             f" · {r['emotion']}" if r["emotion"] else "",
                             f" · «{r['note']}»" if r["note"] else ""])
            out.append(f"{r['ts'][:16].replace('T', ' ')} · {r['meal_type'] or '—'} · "
                       f"голод {r['hunger_before']}→насыщ {r['satiety_after']} · "
                       f"{r['company'] or '—'}{extra}")
        await self._send(uid, "\n".join(out))

    # ------------------------------------------------------------------ polling
    async def start_polling(self) -> None:
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        types = ["message_created", "message_callback", "bot_started"]
        while True:
            try:
                res = await self.client.get_updates(marker=self._marker, timeout=30, types=types)
                for upd in res.get("updates", []):
                    await self.handle(upd)
                self._marker = res.get("marker", self._marker)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("poll loop error")
                await asyncio.sleep(3)


def _num(s: str):
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _loads(s):
    try:
        return json.loads(s or "[]")
    except Exception:
        return []


def _profile_complete(u) -> bool:
    return bool(u and u["sex"] and u["age"] and u["height_cm"] and u["weight_kg"] and u["activity"])


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set")

    async def _run():
        bot = MaxBot()
        with contextlib.suppress(Exception):
            await bot.client.unsubscribe("")  # ignore; ensures polling is allowed
        await bot.start_polling()
        log.info("MAX bot polling…")
        try:
            await asyncio.Event().wait()
        finally:
            await bot.aclose()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
