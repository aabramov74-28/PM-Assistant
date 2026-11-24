"""Смоук-тест ядра без Telegram: БД, матрица эскалаций, дайджест, отчёт.

Запуск: python tests/test_smoke.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect
from app.repository import Repository
from app.services import (build_daily_digest, build_status_report_data,
                          evaluate_reminders, render_status_report_docx)

TODAY = date.today()
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILED
    mark = "✅" if condition else "❌"
    if not condition:
        FAILED += 1
    print(f"{mark} {name}" + (f" — {detail}" if detail and not condition else ""))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(connect(Path(tmp) / "test.db"))

        # --- данные ---
        pm = repo.create_user("Иван Петров", telegram_id=1001,
                              email="pm@example.com", role="pm")
        dev = repo.create_user("Мария Сидорова", telegram_id=1002,
                               email="dev@example.com", role="executor")
        project = repo.create_project("FTX", "Финтех-платформа")

        t_today = repo.create_task(project["id"], "Интеграция с БКИ",
                                   "API скоринга", dev["id"], pm["id"], TODAY)
        t_overdue = repo.create_task(project["id"], "Макет личного кабинета",
                                     "", dev["id"], pm["id"], TODAY - timedelta(days=3))
        t_future = repo.create_task(project["id"], "Настройка CI/CD",
                                    "", dev["id"], pm["id"], TODAY + timedelta(days=2))
        t_stale = repo.create_task(project["id"], "Регламент релизов",
                                   "", dev["id"], pm["id"], TODAY + timedelta(days=10))
        repo.conn.execute("UPDATE tasks SET updated_at=? WHERE id=?",
                          ((datetime.now() - timedelta(days=5))
                           .strftime("%Y-%m-%d %H:%M:%S"), t_stale["id"]))
        repo.conn.commit()

        check("Идентификаторы задач TASK-NNN",
              t_today["code"] == "TASK-001" and t_future["code"] == "TASK-003",
              f"{t_today['code']}, {t_future['code']}")

        # --- матрица эскалаций ---
        events = evaluate_reminders(repo, TODAY)
        types = {(e.rtype, e.task["code"], e.recipient) for e in events}
        check("Напоминание «дедлайн сегодня» исполнителю",
              ("due_day", "TASK-001", "assignee") in types)
        check("Эскалация «просрочка 3+» PM",
              ("overdue_3plus", "TASK-002", "pm") in types)
        check("Напоминание «2 дня до дедлайна»",
              ("due_minus_2", "TASK-003", "assignee") in types)

        # --- идемпотентность журнала напоминаний ---
        repo.log_reminder(t_today["id"], "due_day")
        repo.log_reminder(t_today["id"], "due_day")
        check("Напоминание не дублируется в день",
              repo.reminder_sent_today(t_today["id"], "due_day", TODAY))
        count = repo.conn.execute(
            "SELECT COUNT(*) c FROM reminders_log WHERE task_id=? AND type='due_day'",
            (t_today["id"],)).fetchone()["c"]
        check("В журнале одна запись", count == 1, f"count={count}")

        # --- статусы ---
        repo.set_status(t_today["id"], "in_progress", dev["id"],
                        comment="в работе, 50%", progress=50)
        task = repo.get_task(t_today["id"])
        check("Смена статуса", task["status"] == "in_progress")
        last = repo.last_update(t_today["id"])
        check("Комментарий сохранён", last["comment"] == "в работе, 50%")

        # --- перенос срока ---
        repo.set_deadline(t_overdue["id"], TODAY + timedelta(days=5), pm["id"])
        task = repo.get_task(t_overdue["id"])
        check("Перенос срока",
              task["deadline"] == (TODAY + timedelta(days=5)).isoformat()
              and task["extension_pending"] == 0)

        # --- дайджест ---
        digest = build_daily_digest(repo, TODAY)
        check("Дайджест: разделы",
              all(s in digest for s in ("Выполнено", "Просрочено",
                                        "Дедлайны ближайших 3 дней",
                                        "Зависшие", "Эскалации")))
        check("Дайджест: зависшая задача попала", "TASK-004" in digest)

        # --- отчёт docx ---
        repo.set_status(t_today["id"], "done", pm["id"])
        data = build_status_report_data(
            repo, TODAY - timedelta(days=7), TODAY)
        out = str(Path(tmp) / "report.docx")
        render_status_report_docx(data, out)
        check("Отчёт .docx создан", Path(out).stat().st_size > 5000)

        # --- LLM fallback (без настроек) ---
        from app.integrations.llm import LLMModule
        parsed = LLMModule(repo).parse_status_reply("всё почти готово")
        check("LLM деградация: unclear + комментарий",
              parsed["status"] == "unclear" and parsed["comment"])

        # --- почта без настроек ---
        from app.integrations.mailer import Mailer
        mailer = Mailer(repo)
        check("Почта деградация: send -> False, пишется в аудит",
              mailer.send("x@example.com", "Тест", "текст") is False)
        audited = repo.conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE action='mail_skipped'"
        ).fetchone()["c"]
        check("Аудит почтового пропуска", audited >= 1)

        # --- аудит ---
        total_audit = repo.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        check("Журнал аудита наполняется", total_audit >= 5,
              f"записей: {total_audit}")

    print()
    if FAILED:
        print(f"ПРОВАЛЕНО тестов: {FAILED}")
        sys.exit(1)
    print("Все проверки пройдены ✔")


if __name__ == "__main__":
    main()
