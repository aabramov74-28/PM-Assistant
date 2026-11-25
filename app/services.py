"""Бизнес-логика: напоминания/эскалации (раздел 5.2 ТЗ), дайджесты, отчёты."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .repository import ACTIVE_STATUSES, PRIORITY_LABELS, STATUS_LABELS, Repository

STALE_DAYS = 3  # FR-11: задача без обновлений 3+ дня — «зависшая»

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# ---------------------------------------------------------------- расписания проектов
# Настраиваемая частота проверок исполнения и генерации отчётов (на проект).
FREQUENCY_LABELS = {
    "daily": "1 раз/день",
    "twice_weekly": "2 раза/нед",
    "weekly": "1 раз/нед",
}
# Дни недели срабатывания (0=Пн … 6=Вс)
FREQUENCY_DAYS = {
    "daily": (0, 1, 2, 3, 4),   # будни
    "twice_weekly": (1, 4),     # Вт и Пт
    "weekly": (4,),             # Пт
}
# Глубина периода отчёта
FREQUENCY_PERIOD_DAYS = {"daily": 1, "twice_weekly": 4, "weekly": 7}


def freq_matches(freq: str, day: date) -> bool:
    """Срабатывает ли расписание данной частоты в указанный день."""
    days = FREQUENCY_DAYS.get(freq, FREQUENCY_DAYS["weekly"])
    return day.weekday() in days


def report_period(freq: str, today: date) -> tuple[date, date]:
    """Период отчёта по частоте: (начало, конец)."""
    days = FREQUENCY_PERIOD_DAYS.get(freq, 7)
    return today - timedelta(days=days), today


# ---------------------------------------------------------------- список участников

def parse_member_list(text: str) -> list[dict]:
    """Разбор списка участников для массового добавления (/addteam).

    Формат строки: «Имя Фамилия, @username, email» — username и email
    необязательны, разделитель «,» или «;», порядок полей после имени
    не важен. Строки с «#» — комментарии. Возвращает список словарей
    {line, name, username, email} или {line, error}.
    """
    results: list[dict] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.replace(";", ",").split(",") if p.strip()]
        if not parts:
            continue
        name_parts = [parts[0]]
        username = email = None
        for p in parts[1:]:
            if p.startswith("@"):
                username = p.lstrip("@")
            elif "@" in p and "." in p:
                email = p
            else:
                name_parts.append(p)  # «Иван, Петров, @ivan» → имя из двух частей
        name = " ".join(name_parts).strip()
        if len(name) < 2:
            results.append({"line": lineno, "error": f"не распознано имя: «{line}»"})
        else:
            results.append({"line": lineno, "name": name,
                            "username": username, "email": email})
    return results


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def overdue_days(task, today: date) -> int:
    return (today - date.fromisoformat(task["deadline"])).days


@dataclass
class ReminderEvent:
    """Событие уведомления по матрице раздела 5.2 ТЗ."""
    rtype: str
    task: object
    recipient: str          # 'assignee' | 'pm'
    text: str


def task_line(task, repo: Repository, today: date) -> str:
    assignee = repo.get_user(task["assignee_id"])
    project = repo.get_project(task["project_id"])
    status = STATUS_LABELS.get(task["status"], task["status"])
    od = overdue_days(task, today)
    flag = ""
    if od > 0:
        flag = f"  ⚠️ просрочка {od} дн."
    elif od == 0:
        flag = "  🔥 дедлайн сегодня"
    return (f"{task['code']} — {task['title']}\n"
            f"    {project['name']} · {assignee['name']} · до {fmt_date(task['deadline'])}"
            f" · {status}{flag}")


def evaluate_reminders(repo: Repository, today: date) -> list[ReminderEvent]:
    """Матрица напоминаний и эскалаций (раздел 5.2 ТЗ). Каждое событие — 1 раз в день."""
    events: list[ReminderEvent] = []

    for task in repo.tasks_due_in(2, today):
        events.append(ReminderEvent(
            "due_minus_2", task, "assignee",
            f"📅 Напоминание: до дедлайна 2 дня.\n{task_line(task, repo, today)}\n"
            f"Если всё идёт по плану — просто продолжайте. Проблемы? Ответьте /status {task['code']}"))
    for task in repo.tasks_due_in(1, today):
        events.append(ReminderEvent(
            "due_minus_1", task, "assignee",
            f"⏰ Завтра дедлайн.\n{task_line(task, repo, today)}\n"
            f"Подтвердите готовность: /status {task['code']} или кнопки в запросе завтра."))
    for task in repo.tasks_due_in(0, today):
        events.append(ReminderEvent(
            "due_day", task, "assignee",
            f"🔥 Дедлайн сегодня!\n{task_line(task, repo, today)}\n"
            f"Обновите статус: /status {task['code']}"))  # кнопки добавит бот

    for task in repo.tasks_overdue(today):
        od = overdue_days(task, today)
        if od == 1:
            events.append(ReminderEvent(
                "overdue_1", task, "assignee",
                f"⚠️ Задача просрочена на 1 день.\n{task_line(task, repo, today)}\n"
                f"Обновите статус (/status {task['code']}) или запросите перенос срока."))
        elif od == 2:
            events.append(ReminderEvent(
                "overdue_2", task, "pm",
                f"⚠️ Просрочка 2 дня — требуется внимание.\n{task_line(task, repo, today)}"))
        else:
            events.append(ReminderEvent(
                "overdue_3plus", task, "pm",
                f"🚨 Эскалация: просрочка {od} дн., задача в зоне риска.\n"
                f"{task_line(task, repo, today)}\nРешите: перенести срок, сменить исполнителя, эскалировать."))

    return events


def stale_tasks(repo: Repository, now: datetime) -> list:
    """FR-11: зависшие задачи (без обновлений STALE_DAYS+ дней)."""
    return repo.tasks_stale(STALE_DAYS, now)


# ---------------------------------------------------------------- дайджест

def build_daily_digest(repo: Repository, today: date, llm=None) -> str:
    """FR-16: ежедневный дайджест для PM. LLM (если подключён) пишет резюме дня
    по фактам дайджеста; факты всегда только из БД (FR-19)."""
    now = datetime.now()
    yesterday = now - timedelta(days=1)
    lines: list[str] = [
        f"📋 Дайджест за {today.day:02d}.{today.month:02d}.{today.year} ({WEEKDAYS_RU[today.weekday()]})",
        "",
    ]

    done = repo.tasks_completed_since(yesterday)
    lines.append(f"✅ Выполнено за сутки: {len(done)}")
    for t in done:
        lines.append(f"  · {t['code']} — {t['title']}")

    overdue = repo.tasks_overdue(today)
    lines.append(f"\n⚠️ Просрочено: {len(overdue)}")
    for t in overdue:
        lines.append(f"  · {task_line(t, repo, today)}")

    upcoming = []
    for d in range(0, 4):
        upcoming.extend(repo.tasks_due_in(d, today))
    lines.append(f"\n🔥 Дедлайны ближайших 3 дней: {len(upcoming)}")
    for t in upcoming:
        lines.append(f"  · {task_line(t, repo, today)}")

    stale = stale_tasks(repo, now)
    lines.append(f"\n💤 Зависшие (без обновлений {STALE_DAYS}+ дн.): {len(stale)}")
    for t in stale:
        lines.append(f"  · {task_line(t, repo, today)}")

    escalations = [t for t in overdue if overdue_days(t, today) >= 3]
    lines.append(f"\n🚨 Эскалации (просрочка 3+ дн.): {len(escalations)}")
    for t in escalations:
        lines.append(f"  · {t['code']} — {t['title']}")

    new_tasks = repo.tasks_created_since(yesterday)
    lines.append(f"\n🆕 Новых задач за сутки: {len(new_tasks)}")

    digest = "\n".join(lines)
    if llm is not None:
        summary = llm.summarize(digest, context="Ежедневный дайджест портфеля проектов")
        if summary:
            digest = digest.replace("\n\n", f"\n\n💬 Резюме дня: {summary}\n\n", 1)
    return digest


# ---------------------------------------------------------------- отчёт

def build_status_report_data(repo: Repository, period_start: date, period_end: date,
                             project_id: int | None = None) -> dict:
    """FR-17/FR-18: данные статус-отчёта (все проекты или один)."""
    today = period_end
    projects = []
    scope = ([repo.get_project(project_id)] if project_id
             else repo.list_projects())
    for project in scope:
        if project is None:
            continue
        tasks = repo.list_tasks(project_id=project["id"])
        done = [t for t in tasks if t["status"] == "done"
                and t["updated_at"] >= period_start.isoformat()]
        active = [t for t in tasks if t["status"] in ACTIVE_STATUSES]
        overdue = [t for t in active if date.fromisoformat(t["deadline"]) < today]
        blockers = []
        for t in active:
            if t["status"] == "blocked":
                last = repo.last_update(t["id"])
                blockers.append((t, last["comment"] if last else ""))
        projects.append({
            "project": project,
            "done": done,
            "active": active,
            "overdue": overdue,
            "blockers": blockers,
        })
    return {
        "period_start": period_start,
        "period_end": period_end,
        "projects": projects,
        "generated_at": datetime.now(),
    }


def report_facts_text(data: dict) -> str:
    """Факты отчёта текстом — вход для LLM-резюме (FR-27)."""
    parts = []
    for block in data["projects"]:
        p = block["project"]
        parts.append(
            f"Проект {p['name']}: выполнено {len(block['done'])}, "
            f"в работе {len(block['active'])}, просрочено {len(block['overdue'])}, "
            f"блокеров {len(block['blockers'])}.")
        for t in block["overdue"]:
            parts.append(f"Просрочена {t['code']} — {t['title']}.")
        for t, comment in block["blockers"]:
            parts.append(f"Блокер {t['code']} — {t['title']}"
                         + (f": {comment}." if comment else "."))
    return "\n".join(parts)


def render_status_report_docx(data: dict, path: str, summary: str | None = None) -> str:
    """Еженедельный отчёт .docx (FR-17). Только данные из БД; LLM — лишь резюме."""
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(11)

    doc.add_heading(
        f"Статус-отчёт по проектам: {fmt_date(data['period_start'].isoformat())} — "
        f"{fmt_date(data['period_end'].isoformat())}", level=0)

    if summary:
        intro = doc.add_paragraph()
        intro.add_run("Резюме недели. ").bold = True
        intro.add_run(summary)

    for block in data["projects"]:
        project = block["project"]
        doc.add_heading(f"{project['name']} ({project['code']})", level=1)
        doc.add_paragraph(
            f"Выполнено за период: {len(block['done'])} · "
            f"В работе: {len(block['active'])} · "
            f"Просрочено: {len(block['overdue'])} · "
            f"Заблокировано: {len(block['blockers'])}")

        if block["done"]:
            doc.add_paragraph("Выполнено:", style="List Bullet").bold = True
            for t in block["done"]:
                doc.add_paragraph(f"{t['code']} — {t['title']}", style="List Bullet")
        if block["overdue"]:
            for t in block["overdue"]:
                od = overdue_days(t, data["period_end"])
                doc.add_paragraph(
                    f"Просрочено ({od} дн.): {t['code']} — {t['title']}",
                    style="List Bullet")
        if block["blockers"]:
            for t, comment in block["blockers"]:
                doc.add_paragraph(
                    f"Блокер: {t['code']} — {t['title']}"
                    + (f" ({comment})" if comment else ""), style="List Bullet")

    doc.add_paragraph(
        f"Сформировано автоматически: {data['generated_at'].strftime('%d.%m.%Y %H:%M')}")
    doc.save(path)
    return path
