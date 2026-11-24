"""Планировщик: напоминания/эскалации, дайджест, опрос, недельный отчёт."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes

from .config import Settings, parse_hhmm
from .integrations.calendar_sync import CalendarSync
from .integrations.llm import LLMModule
from .integrations.mailer import Mailer
from .repository import ACTIVE_STATUSES, Repository
from .services import (FREQUENCY_LABELS, build_daily_digest,
                       build_status_report_data, evaluate_reminders,
                       freq_matches, render_status_report_docx,
                       report_facts_text, report_period)

log = logging.getLogger(__name__)


def _tz() -> ZoneInfo:
    return ZoneInfo(Settings.TZ)


def _at(hhmm: str) -> time:
    h, m = parse_hhmm(hhmm)
    return time(h, m, tzinfo=_tz())


# ---------------------------------------------------------------- jobs

async def deadline_check(context) -> None:
    """Ежедневная проверка сроков: матрица напоминаний и эскалаций (5.2 ТЗ)."""
    app: Application = context.application
    r: Repository = app.bot_data["repo"]
    today = date.today()
    sent = 0
    for event in evaluate_reminders(r, today):
        if r.reminder_sent_today(event.task["id"], event.rtype, today):
            continue
        markup = None
        if event.rtype == "due_day":
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Готово",
                                     callback_data=f"qs:done:{event.task['id']}"),
                InlineKeyboardButton("🔨 В работе",
                                     callback_data=f"qs:in_progress:{event.task['id']}"),
                InlineKeyboardButton("⛔ Блокер",
                                     callback_data=f"qs:blocked:{event.task['id']}"),
            ]])
        if event.recipient == "assignee":
            user = r.get_user(event.task["assignee_id"])
            if user and user["telegram_id"]:
                try:
                    await app.bot.send_message(user["telegram_id"], event.text,
                                               reply_markup=markup)
                    sent += 1
                except Exception as exc:
                    log.warning("Доставка не удалась (tg %s): %s",
                                user["telegram_id"], exc)
            elif user and user["email"]:
                # FR-08: исполнитель без Telegram — напоминание по e-mail
                Mailer(r).send(user["email"],
                               f"[{event.task['code']}] Напоминание о сроке",
                               event.text)
                sent += 1
        else:  # pm
            for u in r.list_users():
                if u["role"] in ("pm", "admin") and u["telegram_id"]:
                    try:
                        await app.bot.send_message(u["telegram_id"], event.text,
                                                   reply_markup=markup)
                        sent += 1
                    except Exception as exc:
                        log.warning("Доставка не удалась (tg %s): %s",
                                    u["telegram_id"], exc)
        r.log_reminder(event.task["id"], event.rtype)
    r.audit("deadline_check", None, f"событий: {sent}")
    log.info("deadline_check: отправлено %s уведомлений", sent)


async def daily_digest(context) -> None:
    """FR-16: ежедневный дайджест всем PM (Telegram + e-mail)."""
    app: Application = context.application
    r: Repository = app.bot_data["repo"]
    today = date.today()
    text = build_daily_digest(r, today, llm=LLMModule(r))
    mailer = Mailer(r)
    for pm in r.list_users():
        if pm["role"] not in ("pm", "admin"):
            continue
        if pm["telegram_id"]:
            try:
                await app.bot.send_message(pm["telegram_id"], text)
            except Exception as exc:
                log.warning("Дайджест не доставлен PM %s: %s", pm["id"], exc)
        if pm["email"]:
            mailer.send(pm["email"], f"Дайджест портфеля за {today.isoformat()}",
                        text)
    r.audit("digest_sent", None, f"{today.isoformat()}")


async def eod_survey(context) -> None:
    """FR-12: опрос исполнителей по активным задачам.

    Частота проверок — настройка проекта (check_frequency):
    1 раз/день, 2 раза/нед, 1 раз/нед. Опрос уходит исполнителю только
    по проектам, у которых сегодня день проверки.
    """
    app: Application = context.application
    r: Repository = app.bot_data["repo"]
    today = date.today()
    projects_today = [p for p in r.list_projects()
                      if freq_matches(p["check_frequency"], today)]
    if not projects_today:
        return
    for user in r.list_users("executor"):
        if not user["telegram_id"]:
            continue
        tasks = []
        for project in projects_today:
            tasks.extend(
                t for t in r.list_tasks(assignee_id=user["id"],
                                        project_id=project["id"],
                                        statuses=ACTIVE_STATUSES)
                if t["status"] in ("new", "in_progress", "blocked"))
        if not tasks:
            continue
        lines = [f"👋 Итоги дня, {user['name']}! Коротко по вашим задачам:"]
        markup_rows = []
        for t in tasks:
            lines.append(f"· {t['code']} — {t['title']} (до {t['deadline']})")
            markup_rows.append([
                InlineKeyboardButton(f"🔨 {t['code']} в работе",
                                     callback_data=f"qs:in_progress:{t['id']}"),
                InlineKeyboardButton("✅", callback_data=f"qs:done:{t['id']}"),
                InlineKeyboardButton("⛔", callback_data=f"qs:blocked:{t['id']}"),
            ])
        lines.append("\nОтметьтесь кнопками или напишите: /status TASK-NNN комментарий")
        try:
            await app.bot.send_message(
                user["telegram_id"], "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(markup_rows))
        except Exception as exc:
            log.warning("Опрос не доставлен %s: %s", user["id"], exc)
    r.audit("eod_survey_sent", None,
            f"{today.isoformat()}; проектов: {len(projects_today)}")


async def project_reports(context) -> None:
    """FR-17: статус-отчёты .docx по проектам.

    Задание запускается каждый будний день; отчёт по проекту формируется
    только в дни, заданные его report_frequency (1 раз/день, 2 раза/нед,
    1 раз/нед). Период отчёта зависит от частоты.
    """
    app: Application = context.application
    r: Repository = app.bot_data["repo"]
    today = date.today()
    llm = LLMModule(r)
    mailer = Mailer(r)
    for project in r.list_projects():
        if not freq_matches(project["report_frequency"], today):
            continue
        start, end = report_period(project["report_frequency"], today)
        data = build_status_report_data(r, start, end, project_id=project["id"])
        path = f"status_report_{project['code']}_{today.isoformat()}.docx"
        summary = llm.summarize(
            report_facts_text(data),
            context=f"Статус-отчёт по проекту {project['name']}")
        render_status_report_docx(data, path, summary=summary)
        freq_label = FREQUENCY_LABELS[project["report_frequency"]]
        caption = (f"Статус-отчёт по проекту {project['name']} "
                   f"({project['code']}), {freq_label}. "
                   f"Внешняя рассылка — только после вашего подтверждения.")
        for pm in r.list_users():
            if pm["role"] not in ("pm", "admin"):
                continue
            if pm["telegram_id"]:
                try:
                    with open(path, "rb") as f:
                        await app.bot.send_document(
                            pm["telegram_id"], f,
                            filename=f"Статус-отчёт_{project['code']}_{today.isoformat()}.docx",
                            caption=caption)
                except Exception as exc:
                    log.warning("Отчёт не доставлен PM %s: %s", pm["id"], exc)
            if pm["email"]:
                mailer.send(pm["email"],
                            f"Статус-отчёт {project['code']} {today.isoformat()}",
                            caption, attachment_path=path)
        r.audit("project_report_sent", None,
                f"{project['code']} {start.isoformat()}..{end.isoformat()}")


async def imap_poll(context) -> None:
    """FR-14/FR-25/FR-26: приём ответов исполнителей по e-mail.

    Каждые 15 минут: письма с [TASK-NNN] в теме → разбор LLM → обновление
    статуса. Неразобранное пересылается PM. Дедупликация — reminders_log.
    """
    app: Application = context.application
    r: Repository = app.bot_data["repo"]
    mailer = Mailer(r)
    if not mailer.enabled:
        return
    llm = LLMModule(r)
    from .bot import notify_pms  # импорт здесь, чтобы не тянуть telegram в тесты

    for reply in mailer.fetch_task_replies():
        task = r.get_task_by_code(reply["task_code"])
        if not task:
            continue
        if r.reminder_sent_today(task["id"], "email_reply", date.today()):
            continue  # ответ на это письмо сегодня уже обработан
        r.log_reminder(task["id"], "email_reply", channel="email")

        user = r.get_user_by_email(reply["from_addr"])
        # первая строка ответа — обычно суть; ниже идёт цитата письма Агента
        body = reply["body"].splitlines()[0] if reply["body"] else ""
        parsed = llm.parse_status_reply(body) if body else None

        if parsed and parsed["status"] != "unclear":
            status = "on_review" if parsed["status"] == "done" else parsed["status"]
            r.set_status(task["id"], status,
                         user["id"] if user else None,
                         comment=parsed["comment"], progress=parsed["progress"],
                         channel="email")
            await notify_pms(
                app,
                f"📧 Ответ по почте: {task['code']} — {parsed['status']} "
                f"({reply['from_addr']}): {parsed['comment']}")
        else:
            # FR-26: не смогли разобрать — сохраняем комментарий и эскалируем PM
            r.set_status(task["id"], task["status"],
                         user["id"] if user else None,
                         comment=reply["body"][:500], channel="email")
            await notify_pms(
                app,
                f"📧❓ Не разобрал ответ по {task['code']} от "
                f"{reply['from_addr']}:\n«{reply['body'][:300]}»\n"
                f"Требуется внимание PM.")


async def calendar_retry(context) -> None:
    """FR-23: повторная синхронизация задач, не попавших в календарь."""
    app: Application = context.application
    r: Repository = app.bot_data["repo"]
    sync = CalendarSync(r)
    if not sync.enabled:
        return
    try:
        synced = sync.sync_pending()
        if synced:
            log.info("CalDAV: досинхронизировано задач: %s", synced)
    except Exception as exc:
        r.audit("calendar_error", None, f"sync_pending: {str(exc)[:200]}")


# ---------------------------------------------------------------- setup

def setup_jobs(app: Application) -> None:
    """Регистрация ежедневных заданий в JobQueue."""
    jq = app.job_queue
    jq.run_daily(deadline_check, _at("08:30"), name="deadline_check")
    jq.run_daily(daily_digest, _at(Settings.DIGEST_TIME), name="daily_digest")
    jq.run_daily(eod_survey, _at(Settings.EOD_SURVEY_TIME), name="eod_survey",
                 days=(0, 1, 2, 3, 4))  # будни
    jq.run_daily(project_reports, _at(Settings.WEEKLY_REPORT_TIME),
                 name="project_reports", days=(0, 1, 2, 3, 4))
    jq.run_repeating(imap_poll, interval=900, first=60, name="imap_poll")
    jq.run_repeating(calendar_retry, interval=1800, first=120,
                     name="calendar_retry")
    log.info("Планировщик настроен: digest=%s, survey=%s, reports=%s по будням "
             "(частота — настройка проекта), imap=15 мин, caldav=30 мин (%s)",
             Settings.DIGEST_TIME, Settings.EOD_SURVEY_TIME,
             Settings.WEEKLY_REPORT_TIME, Settings.TZ)
