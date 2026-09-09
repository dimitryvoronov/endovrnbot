"""Tiny sqlite3 data layer. Sync calls are fine at pilot scale."""
import json
import sqlite3
from contextlib import contextmanager, suppress
from pathlib import Path

from .config import DB_PATH, MEDIA_DIR

_SCHEMA = (Path(__file__).resolve().parent / "schema.sql").read_text()


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db() -> None:
    with connect() as db:
        db.executescript(_SCHEMA)


def upsert_user(tg_user_id: int, first_name: str = "") -> sqlite3.Row:
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE tg_user_id=?", (tg_user_id,)).fetchone()
        if row:
            return row
        cur = db.execute(
            "INSERT INTO users (tg_user_id, pseudonym) VALUES (?, ?)",
            (tg_user_id, first_name or None),
        )
        uid = cur.lastrowid
        db.execute("UPDATE users SET patient_code=? WHERE id=?", (f"P-{uid:05d}", uid))
        return db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def get_user(tg_user_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM users WHERE tg_user_id=?", (tg_user_id,)).fetchone()


def delete_user(tg_user_id: int) -> None:
    """Wipe the user's profile, diary entries, and photo files."""
    with connect() as db:
        rows = db.execute(
            "SELECT photo_paths FROM entries WHERE tg_user_id=?", (tg_user_id,)
        ).fetchall()
        db.execute("DELETE FROM entries WHERE tg_user_id=?", (tg_user_id,))
        db.execute("DELETE FROM users WHERE tg_user_id=?", (tg_user_id,))
    for r in rows:
        for name in json.loads(r["photo_paths"] or "[]"):
            with suppress(Exception):
                (MEDIA_DIR / name).unlink()


def update_profile(tg_user_id: int, data: dict) -> None:
    scalar = ["pseudonym", "sex", "age", "height_cm", "weight_kg", "activity",
              "allergies", "dislikes", "consent_ts"]
    sets, vals = [], []
    for f in scalar:
        if data.get(f) is not None:
            sets.append(f"{f}=?")
            vals.append(data[f])
    for f in ("statuses", "meds"):
        if data.get(f) is not None:
            sets.append(f"{f}=?")
            vals.append(json.dumps(data[f], ensure_ascii=False))
    if not sets:
        return
    vals.append(tg_user_id)
    with connect() as db:
        db.execute(f"UPDATE users SET {', '.join(sets)} WHERE tg_user_id=?", vals)


def insert_entry(tg_user_id: int, e: dict) -> int:
    with connect() as db:
        cur = db.execute(
            """INSERT INTO entries
               (tg_user_id, ts, meal_type, hunger_before, satiety_after,
                company, distractions, emotion, photo_paths, note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                tg_user_id,
                e["ts"],
                e.get("meal_type"),
                e.get("hunger_before"),
                e.get("satiety_after"),
                e.get("company"),
                json.dumps(e.get("distractions", []), ensure_ascii=False),
                e.get("emotion"),
                json.dumps(e.get("photo_paths", []), ensure_ascii=False),
                e.get("note", ""),
            ),
        )
        return cur.lastrowid


def list_entries(tg_user_id: int, since_iso: str) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute(
            "SELECT * FROM entries WHERE tg_user_id=? AND ts>=? ORDER BY ts DESC",
            (tg_user_id, since_iso),
        ).fetchall()


def recent_entries(tg_user_id: int, limit: int = 10) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute(
            "SELECT * FROM entries WHERE tg_user_id=? ORDER BY ts DESC LIMIT ?",
            (tg_user_id, limit),
        ).fetchall()


def list_users_summary() -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute(
            """SELECT u.tg_user_id, u.patient_code, u.pseudonym, u.sex, u.age,
                      COUNT(e.id) AS n_entries, MAX(e.ts) AS last_entry
               FROM users u LEFT JOIN entries e ON e.tg_user_id = u.tg_user_id
               GROUP BY u.tg_user_id
               ORDER BY u.id"""
        ).fetchall()


def resolve_user(key: str) -> sqlite3.Row | None:
    """Find a user by patient_code ('P-00001'), Telegram id, or bare number."""
    key = key.strip()
    with connect() as db:
        if key.lower().startswith("p-"):
            return db.execute(
                "SELECT * FROM users WHERE lower(patient_code)=lower(?)", (key,)
            ).fetchone()
        if key.isdigit():
            n = int(key)
            row = db.execute("SELECT * FROM users WHERE tg_user_id=?", (n,)).fetchone()
            return row or db.execute(
                "SELECT * FROM users WHERE patient_code=?", (f"P-{n:05d}",)
            ).fetchone()
    return None
