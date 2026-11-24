"""Тесты почтового модуля с подменой SMTP/IMAP (внешние серверы не вызываются).

Запуск: python tests/test_mail.py
"""

from __future__ import annotations

import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.db import connect
from app.integrations import mailer as mailer_mod
from app.integrations.mailer import Mailer
from app.repository import Repository

FAILED = 0
SENT: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILED
    mark = "✅" if condition else "❌"
    if not condition:
        FAILED += 1
    print(f"{mark} {name}" + (f" — {detail}" if detail and not condition else ""))


# ---------------------------------------------------------------- моки

class FakeSmtpBase:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.tls_started = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.tls_started = True

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        SENT.append({"msg": msg, "tls": self.tls_started, "port": self.port})


class FakeSMTP_SSL(FakeSmtpBase):
    pass


class FakeSMTP(FakeSmtpBase):
    pass


def build_letter(subject: str, sender: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject  # EmailMessage сам кодирует UTF-8 в заголовке
    msg["From"] = sender
    msg.set_content(body)
    return msg.as_bytes()


class FakeIMAP4_SSL:
    """Два непрочитанных: ответ с [TASK-001] и письмо без тега."""

    LETTERS = {
        b"1": build_letter("Re: [TASK-001] Напоминание о сроке",
                           "Мария Сидорова <dev@example.com>",
                           "В работе, готово на 70%\n\n> Исходное письмо..."),
        b"2": build_letter("Обед в пятницу", "colleague@example.com",
                           "Идём в 13:00?"),
    }

    def __init__(self, host, port):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, user, password):
        pass

    def select(self, box):
        pass

    def search(self, charset, criterion):
        return None, [b"1 2"]

    def fetch(self, num, query):
        raw = self.LETTERS[num]
        if "HEADER.FIELDS" in str(query):
            # Реальный сервер вернёт блок заголовков — просто отрезаем его
            headers_block = raw.split(b"\n\n", 1)[0] + b"\n\n"
            return None, [(b"1", headers_block)]
        return None, [(b"1", raw)]


def enable_mail(port: int = 465) -> dict:
    saved = {k: getattr(Settings, k) for k in
             ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
              "IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "MAIL_FROM_ADDRESS")}
    Settings.SMTP_HOST = "smtp.corp.test"
    Settings.SMTP_PORT = port
    Settings.SMTP_USER = "pm-assistant@corp.test"
    Settings.SMTP_PASSWORD = "secret"
    Settings.IMAP_HOST = "imap.corp.test"
    Settings.IMAP_USER = "pm-assistant@corp.test"
    Settings.IMAP_PASSWORD = "secret"
    Settings.MAIL_FROM_ADDRESS = ""
    return saved


def restore_mail(saved: dict) -> None:
    for k, v in saved.items():
        setattr(Settings, k, v)


def main() -> None:
    global FAILED
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(connect(Path(tmp) / "test.db"))
        pm = repo.create_user("Иван Петров", 1001, "pm@example.com", "pm")
        dev = repo.create_user("Мария Сидорова", None, "dev@example.com",
                               "executor")
        project = repo.create_project("FTX", "Финтех-платформа")
        from datetime import date
        task = repo.create_task(project["id"], "Интеграция с БКИ", "",
                                dev["id"], pm["id"], date.today())

        saved = enable_mail(465)
        mailer_mod.smtplib.SMTP_SSL = FakeSMTP_SSL
        mailer_mod.smtplib.SMTP = FakeSMTP
        mailer_mod.imaplib.IMAP4_SSL = FakeIMAP4_SSL

        # --- отправка: 465 → SSL без starttls ---
        mailer = Mailer(repo)
        check("Модуль включён при настройках", mailer.enabled)
        ok = mailer.send("pm@example.com", "Дайджест", "Текст дайджеста")
        check("send() через SSL: успех", ok and len(SENT) == 1)
        msg = SENT[0]["msg"]
        check("From = SMTP_USER", msg["From"] == "pm-assistant@corp.test")
        check("To и Subject корректны",
              msg["To"] == "pm@example.com" and msg["Subject"] == "Дайджест")
        check("SSL-порт: starttls не вызывался", SENT[0]["tls"] is False)

        # --- отправка с вложением ---
        att = Path(tmp) / "report.docx"
        att.write_bytes(b"PK fake docx")
        mailer.send("pm@example.com", "Отчёт", "Во вложении",
                    attachment_path=str(att))
        check("Вложение прикреплено",
              SENT[1]["msg"].get_payload()[1].get_filename() == "report.docx")

        # --- отправка: 587 → STARTTLS ---
        Settings.SMTP_PORT = 587
        mailer.send("pm@example.com", "Тест TLS", "текст")
        check("Порт 587: starttls вызван", SENT[2]["tls"] is True)
        Settings.SMTP_PORT = 465

        # --- приём: IMAP ---
        replies = mailer.fetch_task_replies()
        check("Найден ровно один ответ с тегом", len(replies) == 1,
              f"replies={len(replies)}")
        reply = replies[0]
        check("Тег задачи извлечён", reply["task_code"] == "TASK-001")
        check("Тема декодирована (utf-8)",
              "Напоминание" in reply["subject"], reply["subject"])
        check("Тело письма извлечено", "70%" in reply["body"])

        # --- сопоставление отправителя с пользователем (FR-25) ---
        user = repo.get_user_by_email(reply["from_addr"])
        check("From 'Имя <addr>' → пользователь найден",
              user is not None and user["name"] == "Мария Сидорова")

        # --- деградация без настроек ---
        restore_mail(saved)
        mailer2 = Mailer(repo)
        check("Без настроек: send -> False",
              mailer2.send("x@y.z", "s", "b") is False)
        check("Без настроек: fetch -> []",
              mailer2.fetch_task_replies() == [])
        audited = repo.conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE action='mail_skipped'"
        ).fetchone()["c"]
        check("Пропуск отправки в аудите", audited >= 1)

    print()
    if FAILED:
        print(f"ПРОВАЛЕНО тестов: {FAILED}")
        sys.exit(1)
    print("Все почтовые проверки пройдены ✔")


if __name__ == "__main__":
    main()
