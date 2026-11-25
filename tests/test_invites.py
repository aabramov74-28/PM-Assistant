"""Тесты приглашений: PM регистрирует участника, тот активируется по ссылке.

Запуск: python tests/test_invites.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect
from app.repository import Repository

FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global FAILED
    mark = "✅" if condition else "❌"
    if not condition:
        FAILED += 1
    print(f"{mark} {name}" + (f" — {detail}" if detail and not condition else ""))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        # --- Миграция со старой схемы users (без username/invite_token) ---
        raw = sqlite3.connect(db_path)
        raw.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "telegram_id INTEGER UNIQUE, name TEXT NOT NULL, email TEXT, "
            "role TEXT NOT NULL DEFAULT 'executor', "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
        raw.execute("INSERT INTO users (telegram_id, name, email, role) "
                    "VALUES (1001, 'Старый Пользователь', 'old@x.ru', 'pm')")
        raw.commit()
        raw.close()

        repo = Repository(connect(db_path))
        old = repo.get_user_by_tg(1001)
        check("Миграция users: старые записи целы",
              old["name"] == "Старый Пользователь")

        # --- PM приглашает участника ---
        pm = repo.create_user("Иван Петров", 2001, "pm@example.com", "pm")
        invited = repo.create_invited_user(
            "Мария Сидорова", "executor", pm["id"],
            username="@MSidorova", email="dev@example.com")
        check("Приглашённый: telegram_id пуст",
              invited["telegram_id"] is None)
        check("Приглашённый: токен создан",
              bool(invited["invite_token"]) and len(invited["invite_token"]) >= 8)
        check("Username нормализован (без @, lower)",
              invited["username"] == "msidorova", invited["username"])
        check("Приглашённый виден в списке пользователей",
              any(u["id"] == invited["id"] for u in repo.list_users()))

        # --- Активация по ссылке ---
        found = repo.get_user_by_invite(invited["invite_token"])
        check("Поиск по токену работает", found["id"] == invited["id"])
        repo.link_telegram(invited["id"], 3003, username="MSidorova")
        activated = repo.get_user(invited["id"])
        check("Активация: telegram_id привязан",
              activated["telegram_id"] == 3003)
        check("Активация: токен погашен (одноразовая ссылка)",
              activated["invite_token"] is None)
        check("Повторное использование ссылки невозможно",
              repo.get_user_by_invite(invited["invite_token"]) is None)
        check("get_user_by_tg находит активированного",
              repo.get_user_by_tg(3003)["name"] == "Мария Сидорова")

        # --- Приглашение без username и e-mail ---
        invited2 = repo.create_invited_user("Алексей Ким", "executor", pm["id"])
        check("Приглашение без username/email работает",
              invited2["username"] is None and invited2["email"] is None)

        # --- Аудит ---
        actions = {r["action"] for r in repo.conn.execute(
            "SELECT DISTINCT action FROM audit_log")}
        check("Аудит: user_invited и user_activated зафиксированы",
              {"user_invited", "user_activated"} <= actions)

        # --- Парсер списка участников (/addteam) ---
        from app.services import parse_member_list

        parsed = parse_member_list(
            "# команда пилота\n"
            "Мария Сидорова, @msidorova, m.sidorova@company.ru\n"
            "Алексей Ким\n"
            "Игорь Волков, i.volkov@company.ru\n"
            "Иван, Петров, @ivanpetrov\n"
            "\n")
        valid = [p for p in parsed if "error" not in p]
        check("Парсер: 4 участника, пустая строка и # пропущены",
              len(valid) == 4, f"n={len(valid)}")
        check("Парсер: полная строка",
              valid[0] == {"line": 2, "name": "Мария Сидорова",
                           "username": "msidorova",
                           "email": "m.sidorova@company.ru"}, str(valid[0]))
        check("Парсер: только имя",
              valid[1]["username"] is None and valid[1]["email"] is None)
        check("Парсер: имя + email без username",
              valid[2]["email"] == "i.volkov@company.ru"
              and valid[2]["username"] is None)
        check("Парсер: имя из двух частей без запятой",
              valid[3]["name"] == "Иван Петров"
              and valid[3]["username"] == "ivanpetrov")

        bad = parse_member_list("!\n,\nХ")
        check("Парсер: битые строки → ошибки, мусор пропускается",
              len(bad) == 2 and all("error" in p for p in bad), str(bad))

        # --- Массовое добавление с дедупликацией ---
        created, skipped = [], []
        for m in valid:
            if m["username"] and repo.get_user_by_username(m["username"]):
                skipped.append(m["name"])
                continue
            if m["email"] and repo.get_user_by_email(m["email"]):
                skipped.append(m["name"])
                continue
            created.append(repo.create_invited_user(
                m["name"], "executor", pm["id"],
                username=m["username"], email=m["email"]))
        # «Мария Сидорова» уже приглашена выше с тем же username/email
        check("Дедупликация: существующая Мария пропущена",
              skipped == ["Мария Сидорова"], str(skipped))
        check("Массовое добавление: 3 новых",
              len(created) == 3, f"n={len(created)}")
        check("У каждого нового — свой токен",
              len({u["invite_token"] for u in created}) == 3)

    print()
    if FAILED:
        print(f"ПРОВАЛЕНО тестов: {FAILED}")
        sys.exit(1)
    print("Все проверки приглашений пройдены ✔")


if __name__ == "__main__":
    main()
