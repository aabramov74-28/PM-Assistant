"""Схема базы данных SQLite (раздел 9 ТЗ)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER UNIQUE,
    name         TEXT NOT NULL,
    email        TEXT,
    role         TEXT NOT NULL DEFAULT 'executor'
                 CHECK (role IN ('pm', 'executor', 'admin')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    caldav_calendar_id TEXT,
    check_frequency   TEXT NOT NULL DEFAULT 'daily'
                      CHECK (check_frequency IN ('daily','twice_weekly','weekly')),
    report_frequency  TEXT NOT NULL DEFAULT 'weekly'
                      CHECK (report_frequency IN ('daily','twice_weekly','weekly')),
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT UNIQUE,                   -- TASK-NNN, проставляется сразу после INSERT
    project_id        INTEGER NOT NULL REFERENCES projects(id),
    title             TEXT NOT NULL,
    description       TEXT,
    assignee_id       INTEGER NOT NULL REFERENCES users(id),
    author_id         INTEGER NOT NULL REFERENCES users(id),
    deadline          TEXT NOT NULL,                 -- ISO date YYYY-MM-DD
    status            TEXT NOT NULL DEFAULT 'new'
                      CHECK (status IN ('new','in_progress','on_review','blocked','done','cancelled')),
    priority          TEXT NOT NULL DEFAULT 'normal'
                      CHECK (priority IN ('low','normal','high')),
    calendar_event_id TEXT,
    extension_pending INTEGER NOT NULL DEFAULT 0,    -- 1 = запрошен перенос, ждёт PM
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS status_updates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL REFERENCES tasks(id),
    user_id    INTEGER REFERENCES users(id),
    status     TEXT,
    progress   INTEGER,
    comment    TEXT,
    channel    TEXT NOT NULL DEFAULT 'telegram'      -- telegram | email
               CHECK (channel IN ('telegram','email')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reminders_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    type    TEXT NOT NULL,                           -- due_minus_2 | due_minus_1 | due_day | overdue_1 | overdue_2 | overdue_3plus | stale | digest | weekly_report | eod_survey
    channel TEXT NOT NULL DEFAULT 'telegram',
    sent_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- идемпотентность: одно напоминание данного типа по задаче в день
CREATE UNIQUE INDEX IF NOT EXISTS idx_reminders_daily
    ON reminders_log(task_id, type, date(sent_at));

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    action     TEXT NOT NULL,
    details    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_deadline  ON tasks(deadline);
CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee  ON tasks(assignee_id);
CREATE INDEX IF NOT EXISTS idx_updates_task    ON status_updates(task_id);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Идемпотентные миграции для баз, созданных ранними версиями."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    if "check_frequency" not in cols:
        conn.execute(
            "ALTER TABLE projects ADD COLUMN check_frequency "
            "TEXT NOT NULL DEFAULT 'daily'")
    if "report_frequency" not in cols:
        conn.execute(
            "ALTER TABLE projects ADD COLUMN report_frequency "
            "TEXT NOT NULL DEFAULT 'weekly'")
    conn.commit()


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Открывает соединение и гарантирует схему."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn
