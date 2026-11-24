"""Почтовый модуль (раздел 5.6 ТЗ): SMTP-отправка, IMAP-чтение ответов.

Неделя 4 плана. Без настроек в .env модуль работает в режиме журнала:
сообщения не отправляются, а пишутся в audit_log (деградация, FR-26).

SMTP: порт 465 — SSL, остальные (587) — STARTTLS.
IMAP: читаются только непрочитанные письма с тегом [TASK-NNN] в теме —
ответы на запросы Агента. Чужие письма не трогаем и не помечаем
прочитанными (BODY.PEEK). Письма Агент не удаляет (FR-26).
"""

from __future__ import annotations

import imaplib
import re
import smtplib
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage

from ..config import Settings

TASK_TAG = re.compile(r"\[(TASK-\d{3,})\]")


class Mailer:
    def __init__(self, repo=None):
        self.enabled = Settings.mail_enabled()
        self.repo = repo

    def _log(self, what: str, details: str) -> None:
        if self.repo:
            self.repo.audit(f"mail_{what}", None, details)

    @staticmethod
    def _from_address() -> str:
        return Settings.MAIL_FROM_ADDRESS or Settings.SMTP_USER

    # ---------------------------------------------------------------- отправка

    def send(self, to: str, subject: str, body: str,
             attachment_path: str | None = None) -> bool:
        """SMTP (TLS). Без конфигурации — только журнал. Возвращает успех."""
        if not self.enabled:
            self._log("skipped", f"to={to} subj={subject!r} (модуль не настроен)")
            return False
        try:
            msg = EmailMessage()
            msg["From"] = self._from_address()
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)
            if attachment_path:
                with open(attachment_path, "rb") as f:
                    msg.add_attachment(
                        f.read(), maintype="application",
                        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename=attachment_path.rsplit("/", 1)[-1])
            if Settings.SMTP_PORT == 465:
                with smtplib.SMTP_SSL(Settings.SMTP_HOST, Settings.SMTP_PORT) as smtp:
                    smtp.login(Settings.SMTP_USER, Settings.SMTP_PASSWORD)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(Settings.SMTP_HOST, Settings.SMTP_PORT) as smtp:
                    smtp.starttls()
                    smtp.login(Settings.SMTP_USER, Settings.SMTP_PASSWORD)
                    smtp.send_message(msg)
            self._log("sent", f"to={to} subj={subject!r}")
            return True
        except Exception as exc:
            self._log("error", f"to={to} subj={subject!r}: {str(exc)[:200]}")
            return False

    # ---------------------------------------------------------------- приём

    @staticmethod
    def _decode(value: str | None) -> str:
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    @staticmethod
    def _plain_text(msg) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode("utf-8", "replace")
            return ""
        payload = msg.get_payload(decode=True)
        return payload.decode("utf-8", "replace") if payload else ""

    def fetch_task_replies(self, limit: int = 50) -> list[dict]:
        """IMAP: непрочитанные ответы с тегом [TASK-NNN] в теме.

        Возвращает список словарей {task_code, from_addr, subject, body}.
        Обработанные письма помечаются прочитанными (флаг Seen);
        дедупликация — через reminders_log (email_reply), поэтому повторная
        обработка того же ответа исключена даже при сбое флага.
        Письма без тега не открываются (не помечаются прочитанными).
        """
        if not (Settings.IMAP_HOST and Settings.IMAP_USER and Settings.IMAP_PASSWORD):
            return []
        results: list[dict] = []
        try:
            with imaplib.IMAP4_SSL(Settings.IMAP_HOST, Settings.IMAP_PORT) as imap:
                imap.login(Settings.IMAP_USER, Settings.IMAP_PASSWORD)
                imap.select("INBOX")
                # Тема кодируется, поэтому широкий поиск UNSEEN + фильтр по тегу
                _, data = imap.search(None, "UNSEEN")
                for num in data[0].split()[-limit:]:
                    # Тема без открытия тела — письмо не помечается прочитанным
                    _, hdr = imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
                    header_msg = message_from_bytes(hdr[0][1])
                    subject = self._decode(header_msg.get("Subject"))
                    match = TASK_TAG.search(subject)
                    if not match:
                        continue
                    _, body_data = imap.fetch(num, "(RFC822)")  # +флаг \Seen
                    msg = message_from_bytes(body_data[0][1])
                    results.append({
                        "task_code": match.group(1),
                        "from_addr": self._decode(msg.get("From")),
                        "subject": subject,
                        "body": self._plain_text(msg).strip(),
                    })
            self._log("fetched", f"replies={len(results)}")
        except Exception as exc:
            self._log("error", f"imap: {str(exc)[:200]}")
        return results
