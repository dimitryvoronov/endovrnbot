CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_user_id    INTEGER UNIQUE NOT NULL,
  patient_code  TEXT,
  pseudonym     TEXT,
  sex           TEXT,
  age           INTEGER,
  height_cm     REAL,
  weight_kg     REAL,
  activity      TEXT,
  statuses      TEXT DEFAULT '[]',
  meds          TEXT DEFAULT '[]',
  allergies     TEXT DEFAULT '',
  dislikes      TEXT DEFAULT '',
  consent_ts    TEXT,
  created_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS entries (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_user_id     INTEGER NOT NULL,
  ts             TEXT NOT NULL,                 -- ISO8601 UTC, meal time
  meal_type      TEXT,
  hunger_before  INTEGER,                       -- 0..4
  satiety_after  INTEGER,                       -- 0..4
  company        TEXT,
  distractions   TEXT DEFAULT '[]',             -- JSON array
  emotion        TEXT,
  photo_paths    TEXT DEFAULT '[]',             -- JSON array of filenames in MEDIA_DIR
  note           TEXT DEFAULT '',
  created_at     TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_entries_user_ts ON entries (tg_user_id, ts);
