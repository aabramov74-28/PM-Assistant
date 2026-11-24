"""Синхронизация с Яндекс 360 Календарь по CalDAV (раздел 5.5 ТЗ).

Неделя 4 плана. Односторонняя синхронизация: Агент → Календарь
(событие-дедлайн на каждую задачу; FR-20…FR-23).

Без настроек в .env модуль работает в режиме журнала (деградация, FR-23):
задачи работают, события не создаются. При сбое CalDAV задача остаётся
несинхронизированной (calendar_event_id = NULL) и подхватывается
планировщиком при следующей попытке (sync_pending).
"""

from __future__ import annotations

from datetime import datetime

from ..config import Settings


class CalendarSync:
    def __init__(self, repo=None):
        self.enabled = Settings.calendar_enabled()
        self.repo = repo
        self._client = None

    def _log(self, what: str, details: str) -> None:
        if self.repo:
            self.repo.audit(f"calendar_{what}", None, details)

    # ---------------------------------------------------------------- подключение

    def _get_client(self):
        if self._client is None:
            import caldav
            self._client = caldav.DAVClient(
                url=Settings.CALDAV_URL,
                username=Settings.CALDAV_USER,
                password=Settings.CALDAV_PASSWORD)
        return self._client

    def _calendar_for(self, project=None):
        """Календарь проекта (FR-20) или первый доступный календарь аккаунта.

        projects.caldav_calendar_id хранит URL календаря проекта; если не
        задан — берётся первый календарь principal'а.
        """
        if project and project["caldav_calendar_id"]:
            import caldav
            return caldav.Calendar(client=self._get_client(),
                                   url=project["caldav_calendar_id"])
        principal = self._get_client().principal()
        calendars = principal.calendars()
        if not calendars:
            raise RuntimeError("У пользователя CalDAV нет ни одного календаря")
        return calendars[0]

    # ---------------------------------------------------------------- события

    @staticmethod
    def _event_ics(uid: str, task_code: str, title: str, deadline: str,
                   assignee: str) -> str:
        d = deadline.replace("-", "")
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        return (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//PM Assistant//RU\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\nDTSTAMP:{stamp}\r\n"
            f"DTSTART;VALUE=DATE:{d}\r\nDTEND;VALUE=DATE:{d}\r\n"
            f"SUMMARY:[{task_code}] {title}\r\n"
            f"DESCRIPTION:Дедлайн задачи {task_code}. Исполнитель: {assignee}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )

    def upsert_task_event(self, task, assignee_name: str, project=None) -> str | None:
        """Создать/обновить событие-дедлайн (FR-21, FR-22).

        Возвращает UID события; None — модуль отключён или сбой
        (сбой логируется, задача останется в очереди на sync_pending).
        """
        uid = task["calendar_event_id"] or f"{task['code'].lower()}@pm-assistant"
        if not self.enabled:
            self._log("skipped", f"{task['code']} (модуль не настроен)")
            return None
        try:
            ics = self._event_ics(uid, task["code"], task["title"],
                                  task["deadline"], assignee_name)
            self._calendar_for(project).save_event(ical=ics)
            self._log("upserted", f"{task['code']} uid={uid}")
            return uid
        except Exception as exc:
            # FR-23: сбой фиксируется, синхронизация откладывается
            self._log("error", f"{task['code']}: {str(exc)[:200]}")
            return None

    def delete_task_event(self, task, project=None) -> None:
        """Удалить событие при отмене задачи (FR-22)."""
        if not self.enabled or not task["calendar_event_id"]:
            return
        try:
            event = self._calendar_for(project).event_by_uid(
                task["calendar_event_id"])
            event.delete()
            self._log("deleted", task["code"])
        except Exception as exc:  # событие могли удалить вручную
            self._log("delete_failed", f"{task['code']}: {str(exc)[:200]}")

    def sync_pending(self) -> int:
        """FR-23: повторная синхронизация задач без события в календаре.

        Вызывается планировщиком. Возвращает число успешно синхронизированных.
        """
        if not self.enabled or not self.repo:
            return 0
        synced = 0
        tasks = self.repo.conn.execute(
            """SELECT * FROM tasks
               WHERE calendar_event_id IS NULL
                 AND status IN ('new','in_progress','on_review','blocked')"""
        ).fetchall()
        for task in tasks:
            assignee = self.repo.get_user(task["assignee_id"])
            project = self.repo.get_project(task["project_id"])
            uid = self.upsert_task_event(
                task, assignee["name"] if assignee else "—", project)
            if uid:
                self.repo.set_calendar_event(task["id"], uid)
                synced += 1
        if synced:
            self._log("sync_pending", f"синхронизировано: {synced}")
        return synced

    def healthcheck(self) -> tuple[bool, str]:
        """Проверка подключения к CalDAV (диагностика после заполнения .env)."""
        if not self.enabled:
            return False, "Модуль не настроен: заполните CALDAV_* в .env"
        try:
            calendars = self._get_client().principal().calendars()
            return True, f"OK, календарей доступно: {len(calendars)}"
        except Exception as exc:
            return False, f"Подключение не удалось: {str(exc)[:150]}"
