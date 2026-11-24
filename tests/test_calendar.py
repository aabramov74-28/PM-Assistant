"""Тесты календарного модуля с подменой caldav (внешний сервер не вызывается).

Запуск: python tests/test_calendar.py
"""

from __future__ import annotations

import sys
import tempfile
import types
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.db import connect
from app.integrations.calendar_sync import CalendarSync
from app.repository import Repository

FAILED = 0
SAVED_EVENTS: list[str] = []   # ICS, полученные «сервером»
DELETED_UIDS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILED
    mark = "✅" if condition else "❌"
    if not condition:
        FAILED += 1
    print(f"{mark} {name}" + (f" — {detail}" if detail and not condition else ""))


class FakeEvent:
    def __init__(self, uid):
        self.uid = uid

    def delete(self):
        DELETED_UIDS.append(self.uid)


class FakeCalendar:
    def __init__(self, client=None, url=None):
        self.url = url

    def save_event(self, ical):
        SAVED_EVENTS.append(ical)
        return None

    def event_by_uid(self, uid):
        return FakeEvent(uid)


class FakePrincipal:
    def calendars(self):
        return [FakeCalendar(url="https://caldav.yandex.ru/calendars/main/")]


class FakeDAVClient:
    def __init__(self, url=None, username=None, password=None):
        self.url, self.username = url, username

    def principal(self):
        return FakePrincipal()


class FailingCalendar(FakeCalendar):
    def save_event(self, ical):
        raise ConnectionError("caldav недоступен")


def fake_caldav_module(calendar_cls=FakeCalendar):
    module = types.ModuleType("caldav")
    module.DAVClient = FakeDAVClient
    module.Calendar = calendar_cls
    return module


def enable_caldav() -> dict:
    saved = {k: getattr(Settings, k)
             for k in ("CALDAV_URL", "CALDAV_USER", "CALDAV_PASSWORD")}
    Settings.CALDAV_URL = "https://caldav.yandex.ru"
    Settings.CALDAV_USER = "pm-assistant@yandex.ru"
    Settings.CALDAV_PASSWORD = "app-password"
    return saved


def restore_caldav(saved: dict) -> None:
    for k, v in saved.items():
        setattr(Settings, k, v)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(connect(Path(tmp) / "test.db"))
        pm = repo.create_user("Иван Петров", 1001, "pm@example.com", "pm")
        dev = repo.create_user("Мария Сидорова", 1002, "dev@example.com",
                               "executor")
        project = repo.create_project("FTX", "Финтех-платформа")
        deadline = (date.today() + timedelta(days=5)).isoformat()
        task = repo.create_task(project["id"], "Интеграция с БКИ", "",
                                dev["id"], pm["id"],
                                date.fromisoformat(deadline))

        # --- 1. Без настроек: деградация ---
        sync = CalendarSync(repo)
        check("Без настроек: модуль выключен", not sync.enabled)
        check("Без настроек: upsert -> None",
              sync.upsert_task_event(task, "Мария Сидорова") is None)
        ok, _ = sync.healthcheck()
        check("Без настроек: healthcheck -> False", not ok)

        # --- 2. Создание события ---
        saved = enable_caldav()
        sys.modules["caldav"] = fake_caldav_module()
        sync = CalendarSync(repo)
        uid = sync.upsert_task_event(task, "Мария Сидорова", project)
        check("upsert вернул UID", uid == "task-001@pm-assistant", str(uid))
        check("Событие ушло на «сервер»", len(SAVED_EVENTS) == 1)
        ics = SAVED_EVENTS[0]
        check("ICS: UID", "UID:task-001@pm-assistant" in ics)
        check("ICS: SUMMARY с кодом и названием",
              "SUMMARY:[TASK-001] Интеграция с БКИ" in ics)
        check("ICS: дата дедлайна",
              f"DTSTART;VALUE=DATE:{deadline.replace('-', '')}" in ics)
        check("ICS: исполнитель в описании",
              "Мария Сидорова" in ics)

        # --- 3. Обновление (перенос срока): UID сохраняется ---
        repo.set_calendar_event(task["id"], uid)
        task2 = repo.get_task(task["id"])
        repo.set_deadline(task["id"], date.fromisoformat(deadline)
                          + timedelta(days=7), pm["id"])
        task3 = repo.get_task(task["id"])
        uid2 = sync.upsert_task_event(task3, "Мария Сидорова", project)
        check("При переносе UID сохраняется", uid2 == uid)
        new_d = (date.fromisoformat(deadline) + timedelta(days=7)) \
            .isoformat().replace("-", "")
        check("ICS обновления: новая дата",
              f"DTSTART;VALUE=DATE:{new_d}" in SAVED_EVENTS[-1])

        # --- 4. Удаление при отмене ---
        sync.delete_task_event(task3, project)
        check("Удаление по UID", DELETED_UIDS == [uid], str(DELETED_UIDS))

        # --- 5. sync_pending: подхват несинхронизированных ---
        t2 = repo.create_task(project["id"], "Макет экрана", "",
                              dev["id"], pm["id"], date.today())
        t3 = repo.create_task(project["id"], "Регламент", "",
                              dev["id"], pm["id"], date.today())
        repo.set_status(t3["id"], "done", pm["id"])  # завершённая — не синкаем
        synced = sync.sync_pending()
        check("sync_pending: активная синхронизирована, done пропущена",
              synced == 1, f"synced={synced}")
        check("calendar_event_id проставлен",
              repo.get_task(t2["id"])["calendar_event_id"]
              == "task-002@pm-assistant")
        check("Завершённая задача не синхронизируется",
              repo.get_task(t3["id"])["calendar_event_id"] is None)

        # --- 6. Сбой CalDAV: деградация без исключений, задача ждёт retry ---
        sys.modules["caldav"] = fake_caldav_module(FailingCalendar)

        class FailingClient(FakeDAVClient):
            def principal(self):
                class P:
                    def calendars(self):
                        return [FailingCalendar()]
                return P()
        sys.modules["caldav"].DAVClient = FailingClient

        sync_fail = CalendarSync(repo)
        t4 = repo.create_task(project["id"], "Тестовая задача", "",
                              dev["id"], pm["id"], date.today())
        check("Сбой: upsert -> None, без исключения",
              sync_fail.upsert_task_event(t4, "Мария Сидорова") is None)
        check("Сбой: ошибка в аудите",
              repo.conn.execute(
                  "SELECT COUNT(*) c FROM audit_log "
                  "WHERE action='calendar_error'").fetchone()["c"] >= 1)
        check("Сбой: задача осталась несинхронизированной",
              repo.get_task(t4["id"])["calendar_event_id"] is None)

        # --- 7. healthcheck с живым подключением ---
        sys.modules["caldav"] = fake_caldav_module()
        ok, msg = CalendarSync(repo).healthcheck()
        check("healthcheck -> OK", ok and "1" in msg, msg)

        sys.modules.pop("caldav", None)
        restore_caldav(saved)

    print()
    if FAILED:
        print(f"ПРОВАЛЕНО тестов: {FAILED}")
        sys.exit(1)
    print("Все календарные проверки пройдены ✔")


if __name__ == "__main__":
    main()
