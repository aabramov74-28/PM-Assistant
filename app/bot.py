"""Telegram-бот: регистрация, управление задачами, статусы, отчёты (раздел 5.1 ТЗ)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

from .config import Settings
from .integrations.calendar_sync import CalendarSync
from .integrations.llm import LLMModule
from .repository import ACTIVE_STATUSES, PRIORITY_LABELS, STATUS_LABELS, Repository
from .services import (FREQUENCY_LABELS, build_daily_digest,
                       build_status_report_data, fmt_date, task_line)

log = logging.getLogger(__name__)

# Состояния диалогов
REG_NAME, REG_EMAIL, REG_ROLE = range(3)
(NT_PROJECT, NT_TITLE, NT_DESC, NT_ASSIGNEE, NT_DEADLINE, NT_PRIORITY) = range(10, 16)
ST_TEXT = 20
AM_NAME, AM_USERNAME, AM_EMAIL, AM_ROLE = range(30, 34)

TASK_CODE = re.compile(r"^TASK-\d{3,}$", re.IGNORECASE)


# ---------------------------------------------------------------- helpers

def repo(context: ContextTypes.DEFAULT_TYPE) -> Repository:
    return context.application.bot_data["repo"]


def current_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return repo(context).get_user_by_tg(update.effective_user.id)


def is_pm(user, tg_id: int) -> bool:
    return bool(user and user["role"] in ("pm", "admin")) or tg_id in Settings.ADMIN_TG_IDS


async def notify_pms(app: Application, text: str,
                     reply_markup: InlineKeyboardMarkup | None = None) -> None:
    r: Repository = app.bot_data["repo"]
    for pm in r.list_users():
        if pm["role"] in ("pm", "admin") and pm["telegram_id"]:
            try:
                await app.bot.send_message(pm["telegram_id"], text,
                                           reply_markup=reply_markup)
            except Exception as exc:
                log.warning("Не удалось уведомить PM %s: %s", pm["id"], exc)


def parse_deadline(text: str) -> date | None:
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- /start

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = current_user(update, context)
    if user:
        await update.message.reply_text(
            f"Вы уже зарегистрированы как {user['name']} ({user['role']}).\n"
            f"Команды: /mytasks, /status, /help")
        return ConversationHandler.END
    # Активация по ссылке-приглашению от PM: /start inv_<token>
    if context.args and context.args[0].startswith("inv_"):
        invited = repo(context).get_user_by_invite(context.args[0][4:])
        if invited:
            repo(context).link_telegram(
                invited["id"], update.effective_user.id,
                username=update.effective_user.username)
            await update.message.reply_text(
                f"✅ Аккаунт активирован: {invited['name']} ({invited['role']}).\n"
                f"Теперь вы будете получать задачи и напоминания. "
                f"Команды: /mytasks, /status, /help")
            await notify_pms(
                context.application,
                f"✅ {invited['name']} активировал(а) аккаунт по приглашению.")
            return ConversationHandler.END
        await update.message.reply_text(
            "Ссылка-приглашение недействительна или уже использована. "
            "Зарегистрируемся обычным способом — введите имя и фамилию:")
        return REG_NAME
    await update.message.reply_text(
        "Здравствуйте! Я — Ассистент PM проектного офиса.\n"
        "Для регистрации введите ваше имя и фамилию:")
    return REG_NAME


async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["reg_name"] = update.message.text.strip()
    await update.message.reply_text("Ваш корпоративный e-mail (или «-», чтобы пропустить):")
    return REG_EMAIL


async def reg_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    context.user_data["reg_email"] = None if email == "-" else email
    keyboard = [[
        InlineKeyboardButton("Исполнитель", callback_data="reg_role:executor"),
        InlineKeyboardButton("PM", callback_data="reg_role:pm"),
    ]]
    await update.message.reply_text(
        "Ваша роль:", reply_markup=InlineKeyboardMarkup(keyboard))
    return REG_ROLE


async def reg_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    role = query.data.split(":", 1)[1]
    tg_id = update.effective_user.id
    if tg_id in Settings.ADMIN_TG_IDS:
        role = "admin"
    user = repo(context).create_user(
        name=context.user_data["reg_name"],
        telegram_id=tg_id,
        email=context.user_data["reg_email"],
        role=role,
        username=update.effective_user.username,
    )
    await query.edit_message_text(
        f"✅ Регистрация завершена: {user['name']}, роль «{user['role']}».\n"
        f"Команды: /mytasks, /status, /help")
    return ConversationHandler.END


# ---------------------------------------------------------------- /newproject

async def newproject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ/PM: /newproject CODE Название проекта"""
    user = current_user(update, context)
    if not is_pm(user, update.effective_user.id):
        await update.message.reply_text("Команда доступна PM и администратору.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /newproject CODE Название проекта")
        return
    code, name = context.args[0].upper(), " ".join(context.args[1:])
    try:
        project = repo(context).create_project(code, name)
    except Exception:
        await update.message.reply_text(f"Проект с кодом {code} уже существует.")
        return
    await update.message.reply_text(f"✅ Проект создан: {project['code']} — {project['name']}")


# ------------------------------------------------- /addmember (PM приглашает)

async def addmember_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """PM регистрирует участника заранее; участник активируется по ссылке."""
    user = current_user(update, context)
    if not is_pm(user, update.effective_user.id):
        await update.message.reply_text("Добавлять участников может PM. /start для регистрации.")
        return ConversationHandler.END
    await update.message.reply_text(
        "Добавление участника проекта.\nИмя и фамилия (или /cancel):")
    return AM_NAME


async def am_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["am_name"] = update.message.text.strip()
    await update.message.reply_text(
        "Его @username в Telegram (или «-», если не знаете):")
    return AM_USERNAME


async def am_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["am_username"] = None if text == "-" else text.lstrip("@")
    await update.message.reply_text("Корпоративный e-mail (или «-», чтобы пропустить):")
    return AM_EMAIL


async def am_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["am_email"] = None if text == "-" else text
    keyboard = [[
        InlineKeyboardButton("Исполнитель", callback_data="am_role:executor"),
        InlineKeyboardButton("PM", callback_data="am_role:pm"),
    ]]
    await update.message.reply_text("Роль:", reply_markup=InlineKeyboardMarkup(keyboard))
    return AM_ROLE


async def am_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    pm = current_user(update, context)
    user = repo(context).create_invited_user(
        name=context.user_data["am_name"],
        role=query.data.split(":", 1)[1],
        author_id=pm["id"] if pm else None,
        username=context.user_data["am_username"],
        email=context.user_data["am_email"],
    )
    bot_username = (await context.application.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=inv_{user['invite_token']}"
    uname = f"@{user['username']}" if user["username"] else "username не указан"
    await query.edit_message_text(
        f"✅ Участник добавлен: {user['name']} ({user['role']}, {uname}).\n\n"
        f"Отправьте ему ссылку-приглашение — по ней аккаунт привяжется "
        f"автоматически (бот не может написать первым):\n{link}\n\n"
        f"До активации напоминания будут приходить на e-mail, если он указан.")
    return ConversationHandler.END


# ---------------------------------------------------------------- /newtask

async def newtask_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = current_user(update, context)
    if not is_pm(user, update.effective_user.id):
        await update.message.reply_text("Создавать задачи может PM. /start для регистрации.")
        return ConversationHandler.END
    projects = repo(context).list_projects()
    if not projects:
        await update.message.reply_text(
            "Нет ни одного проекта. Создайте: /newproject CODE Название")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"{p['code']} — {p['name']}",
                                      callback_data=f"nt_project:{p['id']}")]
                for p in projects]
    await update.message.reply_text("Выберите проект:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return NT_PROJECT


async def nt_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["nt_project_id"] = int(query.data.split(":")[1])
    await query.edit_message_text("Название задачи:")
    return NT_TITLE


async def nt_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["nt_title"] = update.message.text.strip()
    await update.message.reply_text("Описание (или «-», чтобы пропустить):")
    return NT_DESC


async def nt_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["nt_desc"] = "" if text == "-" else text
    users = [u for u in repo(context).list_users() if u["role"] in ("executor", "pm")]
    keyboard = [[InlineKeyboardButton(
        u["name"] if u["telegram_id"] else f"{u['name']} ⏳",
        callback_data=f"nt_assignee:{u['id']}")]
        for u in users]
    await update.message.reply_text("Исполнитель:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return NT_ASSIGNEE


async def nt_assignee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["nt_assignee_id"] = int(query.data.split(":")[1])
    await query.edit_message_text("Дедлайн (ДД.ММ.ГГГГ):")
    return NT_DEADLINE


async def nt_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    deadline = parse_deadline(update.message.text)
    if not deadline:
        await update.message.reply_text(
            "Не понял дату. Введите в формате ДД.ММ.ГГГГ, например 30.11.2026:")
        return NT_DEADLINE
    context.user_data["nt_deadline"] = deadline
    keyboard = [[
        InlineKeyboardButton("Низкий", callback_data="nt_prio:low"),
        InlineKeyboardButton("Обычный", callback_data="nt_prio:normal"),
        InlineKeyboardButton("Высокий", callback_data="nt_prio:high"),
    ]]
    await update.message.reply_text("Приоритет:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return NT_PRIORITY


async def nt_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    r = repo(context)
    author = current_user(update, context)
    task = r.create_task(
        project_id=context.user_data["nt_project_id"],
        title=context.user_data["nt_title"],
        description=context.user_data["nt_desc"],
        assignee_id=context.user_data["nt_assignee_id"],
        author_id=author["id"],
        deadline=context.user_data["nt_deadline"],
        priority=query.data.split(":")[1],
    )
    # FR-21: событие в календаре (если модуль настроен)
    calendar = CalendarSync(r)
    assignee = r.get_user(task["assignee_id"])
    project = r.get_project(task["project_id"])
    event_id = calendar.upsert_task_event(task, assignee["name"], project)
    if event_id:
        r.set_calendar_event(task["id"], event_id)

    assignee = r.get_user(task["assignee_id"])
    project = r.get_project(task["project_id"])
    await query.edit_message_text(
        f"✅ Задача создана:\n{task_line(task, r, date.today())}")
    if assignee["telegram_id"]:
        try:
            await context.application.bot.send_message(
                assignee["telegram_id"],
                f"📌 Вам назначена задача:\n{task_line(task, r, date.today())}\n"
                f"Описание: {task['description'] or '—'}\n"
                f"Обновить статус: /status {task['code']}")
        except Exception as exc:
            log.warning("Уведомление исполнителю не доставлено: %s", exc)
    return ConversationHandler.END


# ---------------------------------------------------------------- просмотр

def format_task_list(tasks, r: Repository) -> str:
    if not tasks:
        return "Задач нет."
    return "\n\n".join(task_line(t, r, date.today()) for t in tasks)


async def mytasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = current_user(update, context)
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь: /start")
        return
    tasks = repo(context).list_tasks(assignee_id=user["id"],
                                     statuses=ACTIVE_STATUSES)
    await update.message.reply_text(
        "📋 Ваши активные задачи:\n\n" + format_task_list(tasks, repo(context)))


async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = current_user(update, context)
    if not is_pm(user, update.effective_user.id):
        await update.message.reply_text("Команда доступна PM.")
        return
    r = repo(context)
    tasks = r.list_tasks(statuses=ACTIVE_STATUSES)
    await update.message.reply_text(
        "📋 Активные задачи портфеля:\n\n" + format_task_list(tasks, r))


# ---------------------------------------------------------------- статусы

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = current_user(update, context)
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь: /start")
        return
    if not context.args or not TASK_CODE.match(context.args[0]):
        await update.message.reply_text("Формат: /done TASK-NNN")
        return
    r = repo(context)
    task = r.get_task_by_code(context.args[0])
    if not task:
        await update.message.reply_text("Задача не найдена.")
        return
    r.set_status(task["id"], "on_review", user["id"],
                 comment="Исполнитель отметил готовность")
    await update.message.reply_text(
        f"✅ {task['code']} переведена в статус «На проверке». PM уведомлён.")
    await notify_pms(context.application,
                     f"🔍 На проверку: {task_line(task, r, date.today())}")


async def status_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """FR: /status TASK-NNN [текст] — обновление статуса исполнителем."""
    user = current_user(update, context)
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь: /start")
        return ConversationHandler.END
    if not context.args or not TASK_CODE.match(context.args[0]):
        await update.message.reply_text("Формат: /status TASK-NNN [комментарий]")
        return ConversationHandler.END
    r = repo(context)
    task = r.get_task_by_code(context.args[0])
    if not task:
        await update.message.reply_text("Задача не найдена.")
        return ConversationHandler.END
    context.user_data["st_task_id"] = task["id"]
    if len(context.args) > 1:
        return await _apply_status_text(update, context, " ".join(context.args[1:]))
    await update.message.reply_text(
        f"{task['code']} — {task['title']}\n"
        f"Напишите статус свободным текстом (например: «в работе, готово на 70%, "
        f"жду ответа от безопасности») или /cancel:")
    return ST_TEXT


async def status_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _apply_status_text(update, context, update.message.text.strip())


async def _apply_status_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             text: str) -> int:
    r = repo(context)
    user = current_user(update, context)
    task = r.get_task(context.user_data["st_task_id"])
    llm = LLMModule(r)
    parsed = llm.parse_status_reply(text)

    status = parsed["status"]
    if status == "unclear":
        # FR-13/FR-29: не распознано — сохраняем комментарий, статус не меняем
        r.set_status(task["id"], task["status"], user["id"],
                     comment=parsed["comment"], progress=parsed["progress"])
        await update.message.reply_text(
            "Комментарий сохранён, но статус распознать не удалось — "
            "передал PM на разбор. Чтобы обновить точно, используйте кнопки "
            "в запросе статуса или формулировки: «в работе», «готово», «заблокирована».")
        await notify_pms(context.application,
                         f"❓ Неоднозначный статус по {task['code']} от {user['name']}:\n"
                         f"«{text}»")
        return ConversationHandler.END

    if status == "done":
        status = "on_review"  # исполнитель не закрывает задачу сам
    r.set_status(task["id"], status, user["id"],
                 comment=parsed["comment"], progress=parsed["progress"])
    label = STATUS_LABELS[status]
    extra = f", {parsed['progress']}%" if parsed["progress"] is not None else ""
    await update.message.reply_text(
        f"✅ {task['code']}: статус «{label}»{extra} сохранён.")
    if status in ("on_review", "blocked"):
        await notify_pms(context.application,
                         f"{'🔍' if status == 'on_review' else '⛔'} {task['code']} — "
                         f"{label} ({user['name']}): {parsed['comment']}")
    return ConversationHandler.END


# ------------------------------------------------- перенос срока (FR-06)

async def extend_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Исполнитель: /extend TASK-NNN ДД.ММ.ГГГГ причина — запрос переноса к PM."""
    user = current_user(update, context)
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь: /start")
        return
    if len(context.args) < 2 or not TASK_CODE.match(context.args[0]):
        await update.message.reply_text(
            "Формат: /extend TASK-NNN ДД.ММ.ГГГГ причина")
        return
    r = repo(context)
    task = r.get_task_by_code(context.args[0])
    new_deadline = parse_deadline(context.args[1])
    if not task or not new_deadline:
        await update.message.reply_text("Проверьте код задачи и дату (ДД.ММ.ГГГГ).")
        return
    reason = " ".join(context.args[2:]) or "без указания причины"
    r.set_extension_pending(task["id"], True)
    r.audit("extension_requested", user["id"],
            f"{task['code']} -> {new_deadline.isoformat()} ({reason})")
    await update.message.reply_text(
        f"Запрос на перенос {task['code']} на {fmt_date(new_deadline.isoformat())} "
        f"отправлен PM.")
    keyboard = [[
        InlineKeyboardButton("✅ Одобрить",
                             callback_data=f"ext:yes:{task['id']}:{new_deadline.isoformat()}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"ext:no:{task['id']}:"),
    ]]
    await notify_pms(
        context.application,
        f"📨 Запрос переноса срока от {user['name']}:\n"
        f"{task_line(task, r, date.today())}\n"
        f"Новый срок: {fmt_date(new_deadline.isoformat())}\nПричина: {reason}",
        reply_markup=InlineKeyboardMarkup(keyboard))


async def extend_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, decision, task_id, new_deadline = query.data.split(":", 3)
    r = repo(context)
    pm = current_user(update, context)
    if not is_pm(pm, update.effective_user.id):
        await query.edit_message_text("Решение по переносу принимает PM.")
        return
    task = r.get_task(int(task_id))
    assignee = r.get_user(task["assignee_id"])
    if decision == "yes":
        r.set_deadline(task["id"], date.fromisoformat(new_deadline), pm["id"])
        # FR-22: обновить событие в календаре
        calendar = CalendarSync(r)
        project = r.get_project(task["project_id"])
        updated_task = r.get_task(task["id"])
        uid = calendar.upsert_task_event(updated_task, assignee["name"], project)
        if uid:
            r.set_calendar_event(task["id"], uid)
        await query.edit_message_text(
            f"✅ Перенос одобрен: {task['code']} → {fmt_date(new_deadline)}")
        notice = f"✅ Перенос одобрен: {task['code']} — новый срок {fmt_date(new_deadline)}."
    else:
        r.set_extension_pending(task["id"], False)
        r.audit("extension_rejected", pm["id"], task["code"])
        await query.edit_message_text(f"❌ Перенос {task['code']} отклонён.")
        notice = f"❌ Перенос срока по {task['code']} отклонён PM."
    if assignee["telegram_id"]:
        try:
            await context.application.bot.send_message(assignee["telegram_id"], notice)
        except Exception:
            pass


# ------------------------------------------------- быстрые кнопки статуса

async def quick_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопки из запросов планировщика: qs:<status>:<task_id>."""
    query = update.callback_query
    await query.answer()
    _, status, task_id = query.data.split(":", 2)
    r = repo(context)
    user = current_user(update, context)
    if not user:
        await query.edit_message_text("Сначала зарегистрируйтесь: /start")
        return
    task = r.get_task(int(task_id))
    if status == "done":
        status = "on_review"
    r.set_status(task["id"], status, user["id"], comment="Быстрый ответ")
    await query.edit_message_text(
        f"✅ {task['code']}: статус «{STATUS_LABELS[status]}» сохранён.")
    if status in ("on_review", "blocked"):
        await notify_pms(context.application,
                         f"{'🔍' if status == 'on_review' else '⛔'} "
                         f"{task_line(task, r, date.today())}")


# ------------------------------------------------- настройки проекта

FREQ_ORDER = ("daily", "twice_weekly", "weekly")


def _settings_text(project) -> str:
    return (f"⚙️ Настройки проекта {project['code']} — {project['name']}\n\n"
            f"🔍 Проверки исполнения: {FREQUENCY_LABELS[project['check_frequency']]}\n"
            f"📄 Генерация отчётов: {FREQUENCY_LABELS[project['report_frequency']]}\n\n"
            f"Изменить (1 раз/день, 2 раза/нед, 1 раз/нед):")


def _settings_keyboard(project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔍 {FREQUENCY_LABELS[f]}",
                              callback_data=f"setf:check:{project_id}:{f}")
         for f in FREQ_ORDER],
        [InlineKeyboardButton(f"📄 {FREQUENCY_LABELS[f]}",
                              callback_data=f"setf:report:{project_id}:{f}")
         for f in FREQ_ORDER],
    ])


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """PM: настройка частоты проверок и отчётов по проектам."""
    user = current_user(update, context)
    if not is_pm(user, update.effective_user.id):
        await update.message.reply_text("Команда доступна PM.")
        return
    projects = repo(context).list_projects()
    if not projects:
        await update.message.reply_text(
            "Нет проектов. Создайте: /newproject CODE Название")
        return
    keyboard = [[InlineKeyboardButton(f"{p['code']} — {p['name']}",
                                      callback_data=f"setp:{p['id']}")]
                for p in projects]
    await update.message.reply_text(
        "⚙️ Выберите проект для настройки расписания:",
        reply_markup=InlineKeyboardMarkup(keyboard))


async def settings_project_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    project = repo(context).get_project(int(query.data.split(":")[1]))
    await query.edit_message_text(_settings_text(project),
                                  reply_markup=_settings_keyboard(project["id"]))


async def settings_set_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, kind, project_id, freq = query.data.split(":")
    r = repo(context)
    pm = current_user(update, context)
    if not is_pm(pm, update.effective_user.id):
        await query.edit_message_text("Настройки меняет PM.")
        return
    r.set_project_frequency(int(project_id),
                            **{("check" if kind == "check" else "report"): freq})
    project = r.get_project(int(project_id))
    await query.edit_message_text(
        "✅ Сохранено.\n\n" + _settings_text(project),
        reply_markup=_settings_keyboard(project["id"]))


# ---------------------------------------------------------------- отчёты

async def digest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = current_user(update, context)
    if not is_pm(user, update.effective_user.id):
        await update.message.reply_text("Дайджест доступен PM.")
        return
    await update.message.reply_text(
        build_daily_digest(repo(context), date.today(),
                           llm=LLMModule(repo(context))))


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """FR-18: статус-отчёт .docx по запросу (текущая неделя)."""
    user = current_user(update, context)
    if not is_pm(user, update.effective_user.id):
        await update.message.reply_text("Отчёт доступен PM.")
        return
    r = repo(context)
    today = date.today()
    week_start = today.fromordinal(today.toordinal() - today.weekday())
    data = build_status_report_data(r, week_start, today)
    path = f"status_report_{today.isoformat()}.docx"
    from .services import render_status_report_docx, report_facts_text
    llm = LLMModule(r)
    summary = llm.summarize(report_facts_text(data),
                            context="Еженедельный статус-отчёт портфеля проектов")
    render_status_report_docx(data, path, summary=summary)
    r.audit("report_generated", user["id"], path)
    await update.message.reply_document(
        document=open(path, "rb"),
        filename=f"Статус-отчёт_{today.isoformat()}.docx",
        caption="Статус-отчёт за текущую неделю (сформирован автоматически из базы задач).")


# ---------------------------------------------------------------- прочее

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Команды:\n"
        "/start — регистрация\n"
        "/mytasks — мои активные задачи\n"
        "/status TASK-NNN [текст] — обновить статус\n"
        "/done TASK-NNN — отметить готовность (на проверку PM)\n"
        "/extend TASK-NNN ДД.ММ.ГГГГ причина — запросить перенос срока\n"
        "\nДля PM:\n"
        "/newproject CODE Название — создать проект\n"
        "/addmember — добавить участника (ссылка-приглашение)\n"
        "/newtask — мастер постановки задачи\n"
        "/tasks — активные задачи портфеля\n"
        "/settings — частота проверок и отчётов по проектам\n"
        "/digest — дайджест немедленно\n"
        "/report — статус-отчёт .docx за неделю")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


def register_handlers(app: Application) -> None:
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            REG_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_email)],
            REG_ROLE: [CallbackQueryHandler(reg_role, pattern=r"^reg_role:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    newtask_conv = ConversationHandler(
        entry_points=[CommandHandler("newtask", newtask_start)],
        states={
            NT_PROJECT: [CallbackQueryHandler(nt_project, pattern=r"^nt_project:")],
            NT_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, nt_title)],
            NT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, nt_desc)],
            NT_ASSIGNEE: [CallbackQueryHandler(nt_assignee, pattern=r"^nt_assignee:")],
            NT_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, nt_deadline)],
            NT_PRIORITY: [CallbackQueryHandler(nt_priority, pattern=r"^nt_prio:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    status_conv = ConversationHandler(
        entry_points=[CommandHandler("status", status_start)],
        states={
            ST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, status_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    addmember_conv = ConversationHandler(
        entry_points=[CommandHandler("addmember", addmember_start)],
        states={
            AM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, am_name)],
            AM_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, am_username)],
            AM_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, am_email)],
            AM_ROLE: [CallbackQueryHandler(am_role, pattern=r"^am_role:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(reg_conv)
    app.add_handler(newtask_conv)
    app.add_handler(status_conv)
    app.add_handler(addmember_conv)
    app.add_handler(CommandHandler("newproject", newproject))
    app.add_handler(CommandHandler("mytasks", mytasks))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CallbackQueryHandler(settings_project_cb, pattern=r"^setp:"))
    app.add_handler(CallbackQueryHandler(settings_set_cb, pattern=r"^setf:"))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("extend", extend_cmd))
    app.add_handler(CommandHandler("digest", digest_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(extend_decision, pattern=r"^ext:"))
    app.add_handler(CallbackQueryHandler(quick_status, pattern=r"^qs:"))
