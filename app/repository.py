"""Слой доступа к данным: пользователи, проекты, задачи, статусы, журналы."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

ACTIVE_STATUSES = ("new", "in_progress", "on_review", "blocked")
STATUS_LABELS = {
    "new": "Новая",
    "in_progress": "В работе",
    "on_review": "На проверке",
    "blocked": "Заблокирована",
    "done": "Выполнена",
    "cancelled": "Отменена",
}
PRIORITY_LABELS = {"low": "Низкий", "normal": "Обычный", "high": "Высокий"}


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------- аудит ----------
    def audit(self, action: str, user_id: int | None = None, details: str = "") -> None:
        self.conn.execute(
            "INSERT INTO audit_log (user_id, action, details) VALUES (?,?,?)",
            (user_id, action, details),
        )
        self.conn.commit()

    # ---------- пользователи ----------
    def create_user(self, name: str, telegram_id: int | None, email: str | None,
                    role: str = "executor") -> sqlite3.Row:
        cur = self.conn.execute(
            "INSERT INTO users (name, telegram_id, email, role) VALUES (?,?,?,?)",
            (name, telegram_id, email, role),
        )
        self.conn.commit()
        user = self.get_user(cur.lastrowid)
        self.audit("user_created", user["id"], f"{name} ({role})")
        return user

    def get_user(self, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def get_user_by_tg(self, telegram_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()

    def get_user_by_email(self, email: str) -> sqlite3.Row | None:
        """Поиск по e-mail (из From: может прийти 'Имя <addr@dom>')."""
        addr = email.lower()
        if "<" in addr:
            addr = addr.split("<", 1)[1].rstrip(">")
        return self.conn.execute(
            "SELECT * FROM users WHERE lower(email)=?", (addr.strip(),)).fetchone()

    def list_users(self, role: str | None = None) -> list[sqlite3.Row]:
        if role:
            return self.conn.execute(
                "SELECT * FROM users WHERE role=? ORDER BY name", (role,)).fetchall()
        return self.conn.execute("SELECT * FROM users ORDER BY name").fetchall()

    # ---------- проекты ----------
    def create_project(self, code: str, name: str) -> sqlite3.Row:
        cur = self.conn.execute(
            "INSERT INTO projects (code, name) VALUES (?,?)", (code, name))
        self.conn.commit()
        self.audit("project_created", None, f"{code}: {name}")
        return self.conn.execute("SELECT * FROM projects WHERE id=?",
                                 (cur.lastrowid,)).fetchone()

    def get_project(self, project_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()

    def list_projects(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM projects ORDER BY code").fetchall()

    def set_project_frequency(self, project_id: int, *, check: str | None = None,
                              report: str | None = None) -> None:
        """Настройка частоты проверок исполнения и отчётов проекта."""
        valid = ("daily", "twice_weekly", "weekly")
        changes = []
        if check:
            assert check in valid, f"некорректная частота: {check}"
            self.conn.execute(
                "UPDATE projects SET check_frequency=? WHERE id=?",
                (check, project_id))
            changes.append(f"проверки={check}")
        if report:
            assert report in valid, f"некорректная частота: {report}"
            self.conn.execute(
                "UPDATE projects SET report_frequency=? WHERE id=?",
                (report, project_id))
            changes.append(f"отчёты={report}")
        self.conn.commit()
        if changes:
            project = self.get_project(project_id)
            self.audit("project_frequency_set", None,
                       f"{project['code']}: {', '.join(changes)}")

    # ---------- задачи ----------
    def create_task(self, project_id: int, title: str, description: str,
                    assignee_id: int, author_id: int, deadline: date,
                    priority: str = "normal") -> sqlite3.Row:
        cur = self.conn.execute(
            """INSERT INTO tasks (project_id, title, description, assignee_id,
                                  author_id, deadline, priority)
               VALUES (?,?,?,?,?,?,?)""",
            (project_id, title, description, assignee_id, author_id,
             deadline.isoformat(), priority),
        )
        code = f"TASK-{cur.lastrowid:03d}"
        self.conn.execute("UPDATE tasks SET code=? WHERE id=?", (code, cur.lastrowid))
        self.conn.commit()
        self.audit("task_created", author_id, f"{code}: {title}")
        return self.get_task(cur.lastrowid)

    def get_task(self, task_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()

    def get_task_by_code(self, code: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE code=?", (code.upper(),)).fetchone()

    def list_tasks(self, *, assignee_id: int | None = None,
                   project_id: int | None = None,
                   statuses: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if assignee_id is not None:
            sql += " AND assignee_id=?"
            params.append(assignee_id)
        if project_id is not None:
            sql += " AND project_id=?"
            params.append(project_id)
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            params.extend(statuses)
        sql += " ORDER BY deadline, id"
        return self.conn.execute(sql, params).fetchall()

    def set_status(self, task_id: int, status: str, user_id: int | None,
                   comment: str = "", progress: int | None = None,
                   channel: str = "telegram") -> None:
        self.conn.execute(
            "UPDATE tasks SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, task_id))
        self.conn.execute(
            """INSERT INTO status_updates (task_id, user_id, status, progress, comment, channel)
               VALUES (?,?,?,?,?,?)""",
            (task_id, user_id, status, progress, comment, channel))
        self.conn.commit()
        task = self.get_task(task_id)
        self.audit("status_changed", user_id,
                   f"{task['code']} -> {status}" + (f" ({comment})" if comment else ""))

    def set_deadline(self, task_id: int, deadline: date, user_id: int | None) -> None:
        task = self.get_task(task_id)
        self.conn.execute(
            "UPDATE tasks SET deadline=?, extension_pending=0, updated_at=datetime('now') WHERE id=?",
            (deadline.isoformat(), task_id))
        self.conn.commit()
        self.audit("deadline_changed", user_id,
                   f"{task['code']}: {task['deadline']} -> {deadline.isoformat()}")

    def set_extension_pending(self, task_id: int, pending: bool) -> None:
        self.conn.execute(
            "UPDATE tasks SET extension_pending=?, updated_at=datetime('now') WHERE id=?",
            (1 if pending else 0, task_id))
        self.conn.commit()

    def set_calendar_event(self, task_id: int, event_id: str | None) -> None:
        self.conn.execute(
            "UPDATE tasks SET calendar_event_id=? WHERE id=?", (event_id, task_id))
        self.conn.commit()

    def cancel_task(self, task_id: int, user_id: int | None) -> None:
        self.set_status(task_id, "cancelled", user_id)

    # ---------- выборки для планировщика и отчётов ----------
    def tasks_due_in(self, days: int, today: date) -> list[sqlite3.Row]:
        target = (today + timedelta(days=days)).isoformat()
        return self.conn.execute(
            f"""SELECT * FROM tasks WHERE deadline=?
                AND status IN ({','.join('?' * len(ACTIVE_STATUSES))})""",
            (target, *ACTIVE_STATUSES)).fetchall()

    def tasks_overdue(self, today: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            f"""SELECT * FROM tasks WHERE deadline < ?
                AND status IN ({','.join('?' * len(ACTIVE_STATUSES))})
                ORDER BY deadline""",
            (today.isoformat(), *ACTIVE_STATUSES)).fetchall()

    def tasks_stale(self, days: int, now: datetime) -> list[sqlite3.Row]:
        threshold = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        return self.conn.execute(
            f"""SELECT * FROM tasks WHERE updated_at < ?
                AND status IN ({','.join('?' * len(ACTIVE_STATUSES))})
                ORDER BY updated_at""",
            (threshold, *ACTIVE_STATUSES)).fetchall()

    def tasks_completed_since(self, since: datetime) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT * FROM tasks WHERE status='done' AND updated_at >= ?
               ORDER BY updated_at""",
            (since.strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()

    def tasks_created_since(self, since: datetime) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE created_at >= ? ORDER BY id",
            (since.strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()

    def last_update(self, task_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """SELECT su.*, u.name AS user_name FROM status_updates su
               LEFT JOIN users u ON u.id = su.user_id
               WHERE su.task_id=? ORDER BY su.id DESC LIMIT 1""",
            (task_id,)).fetchone()

    # ---------- журнал напоминаний ----------
    def reminder_sent_today(self, task_id: int, rtype: str, today: date) -> bool:
        row = self.conn.execute(
            """SELECT 1 FROM reminders_log
               WHERE task_id=? AND type=? AND date(sent_at)=date(?)""",
            (task_id, rtype, today.isoformat())).fetchone()
        return row is not None

    def log_reminder(self, task_id: int, rtype: str, channel: str = "telegram") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO reminders_log (task_id, type, channel) VALUES (?,?,?)",
            (task_id, rtype, channel))
        self.conn.commit()
