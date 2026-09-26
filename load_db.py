"""Загружает events.json в SQLite (funnel.db), чтобы считать воронку SQL-запросами из sql/queries.sql.

Таблица events: ключевые поля события вынесены в колонки, остальное лежит в JSON-колонке properties
и достаётся через json_extract(). Запуск: python3 load_db.py
"""
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "funnel.db")

SCHEMA = """
DROP TABLE IF EXISTS events;
CREATE TABLE events (
    event_id    TEXT PRIMARY KEY,
    event_name  TEXT NOT NULL,
    ts          TEXT NOT NULL,   -- ISO 8601 с часовым поясом, как приходит из POST /v1/events
    event_date  TEXT NOT NULL,   -- локальная дата события (первые 10 символов ts)
    user_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    channel     TEXT,
    device      TEXT,
    city        TEXT,
    properties  TEXT NOT NULL    -- JSON
);
CREATE INDEX idx_events_user ON events (user_id, ts);
CREATE INDEX idx_events_name ON events (event_name);
"""


def main():
    with open(os.path.join(HERE, "events.json"), encoding="utf-8") as f:
        events = json.load(f)

    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                e["event_id"],
                e["event_name"],
                e["ts"],
                e["ts"][:10],
                e["user_id"],
                e["session_id"],
                e["source"]["channel"],
                e["source"]["device"],
                e["source"]["city"],
                json.dumps(e["properties"], ensure_ascii=False),
            )
            for e in events
        ],
    )
    con.commit()
    n_users = con.execute("SELECT COUNT(DISTINCT user_id) FROM events").fetchone()[0]
    print(f"funnel.db: {len(events)} событий, {n_users} пользователей")
    con.close()


if __name__ == "__main__":
    main()
