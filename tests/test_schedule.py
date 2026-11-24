"""Тесты настраиваемых расписаний проектов (частота проверок и отчётов).

Запуск: python tests/test_schedule.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect
from app.repository import Repository
from app.services import (FREQUENCY_LABELS, build_status_report_data,
                          freq_matches, report_period)

FAILED = 0
# Контрольные даты: Пн 16.11.2026 … Пт 20.11.2026
MONDAY = date(2026, 11, 16)
TUESDAY = date(2026, 11, 17)
FRIDAY = date(2026, 11, 20)
SATURDAY = date(2026, 11, 21)


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILED
    mark = "✅" if condition else "❌"
    if not condition:
        FAILED += 1
    print(f"{mark} {name}" + (f" — {detail}" if detail and not condition else ""))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        # --- 1. Миграция со старой схемы (без новых колонок) ---
        raw = sqlite3.connect(db_path)
        raw.execute(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, "
            "caldav_calendar_id TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
        raw.execute("INSERT INTO projects (code, name) VALUES ('OLD', 'Старый проект')")
        raw.commit()
        raw.close()

        repo = Repository(connect(db_path))
        old = repo.conn.execute("SELECT * FROM projects WHERE code='OLD'").fetchone()
        check("Миграция: check_frequency добавлена со значением daily",
              old["check_frequency"] == "daily")
        check("Миграция: report_frequency добавлена со значением weekly",
              old["report_frequency"] == "weekly")

        # --- 2. Новая БД: значения по умолчанию ---
        pm = repo.create_user("Иван Петров", 1001, "pm@example.com", "pm")
        dev = repo.create_user("Мария Сидорова", 1002, "dev@example.com", "executor")
        p1 = repo.create_project("FTX", "Финтех-платформа")
        p2 = repo.create_project("CRD", "Кредитный конвейер")
        check("Новый проект: дефолты daily/weekly",
              p1["check_frequency"] == "daily" and p1["report_frequency"] == "weekly")

        # --- 3. Установка частот ---
        repo.set_project_frequency(p1["id"], check="twice_weekly", report="daily")
        p1 = repo.get_project(p1["id"])
        check("set_project_frequency: обе частоты обновлены",
              p1["check_frequency"] == "twice_weekly"
              and p1["report_frequency"] == "daily")
        repo.set_project_frequency(p2["id"], report="weekly")
        p2 = repo.get_project(p2["id"])
        check("Частичное обновление: только report, check не тронут",
              p2["report_frequency"] == "weekly" and p2["check_frequency"] == "daily")
        audited = repo.conn.execute(
            "SELECT COUNT(*) c FROM audit_log "
            "WHERE action='project_frequency_set'").fetchone()["c"]
        check("Изменения расписаний пишутся в аудит", audited == 2)

        # --- 4. Матрица срабатываний ---
        cases = [
            ("daily", MONDAY, True), ("daily", FRIDAY, True),
            ("daily", SATURDAY, False),
            ("twice_weekly", TUESDAY, True), ("twice_weekly", FRIDAY, True),
            ("twice_weekly", MONDAY, False),
            ("weekly", FRIDAY, True), ("weekly", TUESDAY, False),
            ("weekly", SATURDAY, False),
        ]
        for freq, day, expected in cases:
            check(f"freq_matches({freq}, {day.strftime('%a %d.%m')}) = {expected}",
                  freq_matches(freq, day) is expected)

        # --- 5. Периоды отчётов ---
        start, end = report_period("daily", FRIDAY)
        check("daily: период = 1 день", (end - start).days == 1)
        start, end = report_period("twice_weekly", FRIDAY)
        check("twice_weekly: период = 4 дня", (end - start).days == 4)
        start, end = report_period("weekly", FRIDAY)
        check("weekly: период = 7 дней", (end - start).days == 7
              and end == FRIDAY)

        # --- 6. Отчёт по одному проекту ---
        repo.create_task(p1["id"], "Задача FTX", "", dev["id"], pm["id"], FRIDAY)
        repo.create_task(p2["id"], "Задача CRD", "", dev["id"], pm["id"], FRIDAY)
        data_all = build_status_report_data(repo, FRIDAY - timedelta(days=7), FRIDAY)
        data_one = build_status_report_data(repo, FRIDAY - timedelta(days=1),
                                            FRIDAY, project_id=p1["id"])
        check("Отчёт по портфелю: все проекты (OLD + FTX + CRD)",
              len(data_all["projects"]) == 3, f"n={len(data_all['projects'])}")
        check("Отчёт по проекту: только выбранный",
              len(data_one["projects"]) == 1
              and data_one["projects"][0]["project"]["code"] == "FTX")
        check("Задачи другого проекта не попали",
              all(t["title"] == "Задача FTX"
                  for t in data_one["projects"][0]["active"]))

        check("Все частоты имеют подписи",
              set(FREQUENCY_LABELS) == {"daily", "twice_weekly", "weekly"})

    print()
    if FAILED:
        print(f"ПРОВАЛЕНО тестов: {FAILED}")
        sys.exit(1)
    print("Все проверки расписаний пройдены ✔")


if __name__ == "__main__":
    main()
