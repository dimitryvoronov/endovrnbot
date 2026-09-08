"""Tiny sqlite3 data layer. Sync calls are fine at pilot scale."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH

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
