import fs from "node:fs";
import path from "node:path";
import {
  AlignmentType, Document, Footer, Header, HeadingLevel,
  ImportedXmlComponent, LevelFormat, Packer, PageBreak, PageNumber,
  Paragraph, ShadingType, Table, TableCell, TableRow, TextRun,
  WidthType, convertInchesToTwip,
} from "docx";

const outputPath = process.argv[2];
if (!outputPath) throw new Error("Usage: node create_plan.js /abs/output.docx");

const T = String.raw;
const palette = { dark: "263238", primary: "37474F", light: "78909C", fill: "EEF3F6" };
const font = { ascii: "Times New Roman", hAnsi: "Times New Roman", cs: "Times New Roman", eastAsia: "SimSun" };
const monoFont = { ascii: "Courier New", hAnsi: "Courier New", cs: "Courier New", eastAsia: "SimSun" };

const run = (text, options = {}) => new TextRun({ text, font, size: 24, ...options });
const para = (children, options = {}) => new Paragraph({
  spacing: { after: 160, line: 300 }, ...options,
  children: Array.isArray(children) ? children : [children],
});
const body = (text) => para(run(text), { indent: { firstLine: convertInchesToTwip(0.33) } });
const h1 = (text) => para(run(text, { bold: true, size: 30, color: palette.dark }), {
  heading: HeadingLevel.HEADING_1, spacing: { before: 320, after: 140 },
});
const h2 = (text) => para(run(text, { bold: true, size: 26, color: palette.primary }), {
  heading: HeadingLevel.HEADING_2, spacing: { before: 260, after: 120 },
});
const bullet = (text) => para(run(text), {
  numbering: { reference: "bullets", level: 0 }, spacing: { after: 80, line: 300 },
});
const code = (text) => para(new TextRun({ text, font: monoFont, size: 18 }), {
  spacing: { after: 40, line: 240 },
  indent: { left: convertInchesToTwip(0.3) },
  shading: { type: ShadingType.CLEAR, fill: "F5F7F8" },
});

const cell = (text, options = {}) => new TableCell({
  children: [para(run(text), { spacing: { after: 40, line: 264 } })],
  margins: { top: 100, bottom: 100, left: 120, right: 120 },
  ...options,
});
const makeTable = (widths, header, rows) => new Table({
  width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
  columnWidths: widths,
  rows: [
    new TableRow({ children: header.map((t, i) => cell(t, {
      shading: { type: ShadingType.CLEAR, fill: palette.fill },
      width: { size: widths[i], type: WidthType.DXA },
    })) }),
    ...rows.map((r) => new TableRow({
      children: r.map((t, i) => cell(t, { width: { size: widths[i], type: WidthType.DXA } })),
    })),
  ],
});

const xmlEscape = (v) => String(v).replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
const toc = (entries) => {
  const cached = entries.map(({ title, level, page }) => {
    const indent = Math.max(0, level - 1) * 360;
    return `<w:p><w:pPr><w:pStyle w:val="TOC${level}"/>
      <w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9000"/></w:tabs>
      <w:ind w:left="${indent}"/></w:pPr>
      <w:r><w:t>${xmlEscape(title)}</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>${page}</w:t></w:r></w:p>`;
  }).join("");
  return ImportedXmlComponent.fromXmlString(`<w:sdt xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:sdtPr><w:alias w:val="Содержание"/></w:sdtPr>
    <w:sdtContent>
      <w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/>
        <w:instrText xml:space="preserve"> TOC \\o &quot;1-2&quot; \\h \\z \\u </w:instrText>
        <w:fldChar w:fldCharType="separate"/></w:r></w:p>
      ${cached}
      <w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>
    </w:sdtContent>
  </w:sdt>`).root[0];
};

const tocEntries = [
  { title: T`1. Цель и область плана`, level: 1, page: 3 },
  { title: T`2. Предварительные условия`, level: 1, page: 3 },
  { title: T`3. Инфраструктура`, level: 1, page: 4 },
  { title: T`4. Доступы и секреты`, level: 1, page: 4 },
  { title: T`5. Сетевые доступы`, level: 1, page: 5 },
  { title: T`6. Безопасность и согласование с ИБ`, level: 1, page: 5 },
  { title: T`7. Шаги развёртывания`, level: 1, page: 6 },
  { title: T`8. Эксплуатация: бэкапы, мониторинг, обновления`, level: 1, page: 7 },
  { title: T`9. План пилота и критерии успеха`, level: 1, page: 8 },
  { title: T`10. Риски и митигация`, level: 1, page: 9 },
  { title: T`11. Чек-лист готовности (Go / No-Go)`, level: 1, page: 9 },
  { title: T`Приложение А. Пример systemd unit`, level: 1, page: 10 },
];

const children = [];

// ---------- Cover ----------
children.push(
  para(run(T`ПЛАН РАЗВЁРТЫВАНИЯ`, { bold: true, size: 44, color: palette.dark }), {
    alignment: AlignmentType.CENTER, spacing: { before: 2800, after: 240 },
  }),
  para(run(T`MVP ИИ-агента «Ассистент PM» в продуктивную среду`, { bold: true, size: 32, color: palette.primary }), {
    alignment: AlignmentType.CENTER, spacing: { after: 160 },
  }),
  para(run(T`Инфраструктура · доступы · безопасность · эксплуатация · пилот`, { size: 24, color: palette.light }), {
    alignment: AlignmentType.CENTER, spacing: { after: 480 },
  }),
  para(run(T`Версия 1.0  ·  24 ноября 2026 г.`, { size: 22, color: palette.light }), {
    alignment: AlignmentType.CENTER, spacing: { after: 120 },
  }),
  para(run(T`Проектный офис · проекты разработки финтех- и финансовых продуктов`, { size: 22, color: palette.light }), {
    alignment: AlignmentType.CENTER,
  }),
  new Paragraph({ children: [new PageBreak()] }),
);

// ---------- TOC ----------
children.push(
  para(run(T`Содержание`, { bold: true, size: 30, color: palette.dark }), {
    heading: HeadingLevel.HEADING_1, spacing: { before: 240, after: 120 },
  }),
  para(run(T`Для обновления номеров страниц: правый клик по содержанию → «Обновить поле».`, { italics: true, color: palette.light })),
  toc(tocEntries),
  new Paragraph({ children: [new PageBreak()] }),
);

// ---------- 1 ----------
children.push(h1(T`1. Цель и область плана`));
children.push(body(T`Документ описывает всё необходимое для перевода MVP «Ассистент PM» из разработки в продуктивную эксплуатацию: инфраструктуру, доступы, согласования с ИБ, шаги установки, эксплуатационный контур и план пилота. План рассчитан на развёртывание одного экземпляра сервиса в контуре компании за 5–10 рабочих дней (без учёта времени на согласования ИБ).`));
children.push(body(T`Состав MVP: Telegram-бот, планировщик напоминаний и эскалаций, сбор статусов, дайджесты и отчёты .docx, почта (IMAP/SMTP), Яндекс 360 Календарь (CalDAV), LLM (YandexGPT, OpenAI-совместимый API). Технические детали — в ТЗ (ТЗ_MVP_Ассистент_PM.docx).`));

// ---------- 2 ----------
children.push(h1(T`2. Предварительные условия`));
children.push(bullet(T`Согласование ИБ: состав данных (персональные — ФИО, e-mail, Telegram ID; проектные — названия и статусы задач), передача текстов статусов во внешний LLM, работа с Telegram как корпоративным каналом.`));
children.push(bullet(T`Выделен сервер или ВМ в контуре компании (требования — раздел 3).`));
children.push(bullet(T`Открыты исходящие сетевые доступы (раздел 5) — заявка в ИТ/ИБ.`));
children.push(bullet(T`Созданы сервисные учётные записи: почтовый ящик агента, аккаунт Яндекс 360 для календаря, сервисный аккаунт Yandex Cloud (раздел 4).`));
children.push(bullet(T`Назначен владелец сервиса (администратор) и дежурный контакт поддержки.`));
children.push(bullet(T`Определён пилотный контур: 1–2 проекта, 5–10 исполнителей, 1 PM.`));

// ---------- 3 ----------
children.push(h1(T`3. Инфраструктура`));
children.push(makeTable(
  [3200, 5800],
  [T`Компонент`, T`Требование`],
  [
    [T`Сервер / ВМ`, T`Linux (Ubuntu 22.04+ / Astra), 1 vCPU, 1 ГБ RAM, 10 ГБ диск; размещение в контуре компании`],
    [T`ПО`, T`Python 3.11+, git; зависимости из requirements.txt (python-telegram-bot, APScheduler, caldav, httpx, python-docx)`],
    [T`База данных`, T`SQLite (файл на сервере); ежедневный бэкап — раздел 8`],
    [T`Запуск`, T`systemd unit с автоперезапуском (пример — Приложение А); логи в journald`],
    [T`Часовой пояс`, T`Europe/Moscow на сервере и в конфигурации (TZ в .env)`],
    [T`Время`, T`Синхронизация NTP — напоминания и дайджесты зависят от точного времени`],
  ],
));

// ---------- 4 ----------
children.push(h1(T`4. Доступы и секреты`));
children.push(makeTable(
  [2600, 3600, 2800],
  [T`Секрет`, T`Где получить`, T`Кто выдаёт`],
  [
    [T`TELEGRAM_BOT_TOKEN`, T`@BotFather → /newbot; режим приватности — отключить для групповых чатов (BotFather → Bot Settings → Group Privacy → Off)`, T`PM / администратор`],
    [T`SMTP_/IMAP_*`, T`Сервисный ящик pm-assistant@company.ru; при 2FA — пароль приложения`, T`ИТ (почтовая служба)`],
    [T`CALDAV_*`, T`Яндекс ID → Безопасность → Пароли приложений → «Календарь»; логин — полный адрес user@company.ru`, T`Владелец календаря`],
    [T`LLM_*`, T`Yandex Cloud: сервисный аккаунт с ролью ai.languageModels.user → API-ключ; folder_id каталога`, T`Администратор облака`],
    [T`ADMIN_TG_IDS`, T`Telegram ID администраторов (узнать у @userinfobot)`, T`Администратор`],
  ],
));
children.push(body(T`Хранение: все секреты — только в .env на сервере (права 600, владелец — сервисная учётная запись). .env не коммитится в git (есть в .gitignore), не пересылается по почте и мессенджерам. Ротация секретов — при увольнении владельца и не реже раза в год.`));

// ---------- 5 ----------
children.push(h1(T`5. Сетевые доступы`));
children.push(body(T`С сервера требуются исходящие HTTPS-соединения (порт 443), если не указано иное:`));
children.push(makeTable(
  [3000, 3200, 2800],
  [T`Направление`, T`Адрес`, T`Назначение`],
  [
    [T`Telegram Bot API`, T`api.telegram.org:443`, T`бот: команды, уведомления, кнопки`],
    [T`YandexGPT`, T`llm.api.cloud.yandex.net:443`, T`разбор ответов, резюме отчётов`],
    [T`Яндекс CalDAV`, T`caldav.yandex.ru:443`, T`события-дедлайны в календаре`],
    [T`Корпоративная почта SMTP`, T`smtp.<company>.ru:465/587`, T`отправка дайджестов и отчётов`],
    [T`Корпоративная почта IMAP`, T`imap.<company>.ru:993`, T`приём ответов исполнителей`],
  ],
));
children.push(body(T`Важно: если политика компании ограничивает доступ к Telegram, потребуется решение ИБ (выделенный прокси) или перенос основного канала на корпоративный мессенджер — это отдельная доработка, в MVP не входит. Входящие подключения серверу не нужны: бот работает в режиме polling.`));

// ---------- 6 ----------
children.push(h1(T`6. Безопасность и согласование с ИБ`));
children.push(bullet(T`Классификация данных: персональные данные сотрудников (ФИО, e-mail, Telegram ID), проектные данные (названия задач, статусы, комментарии). Базы и бэкапы — на сервере в контуре.`));
children.push(bullet(T`Передача в LLM: во внешний YandexGPT уходят только тексты статусов и агрегированные факты отчётов. До пилота с ИБ согласуется перечень допустимых данных; при запрете — агент работает без LLM (деградированный режим, FR-29).`));
children.push(bullet(T`Аудит: все действия агента и пользователей пишутся в журнал (таблица audit_log) — доступ администратору и ИБ по запросу.`));
children.push(bullet(T`Доступ к серверу: SSH по ключам, только администратор и ИТ; sudo — по регламенту компании.`));
children.push(bullet(T`Telegram-бот: токен приравнен к паролю; при компрометации — отзыв у @BotFather (/revoke) и перевыпуск.`));
children.push(bullet(T`Резервные копии БД содержат те же данные — хранятся с тем же уровнем доступа, срок хранения по регламенту компании.`));

// ---------- 7 ----------
children.push(h1(T`7. Шаги развёртывания`));
children.push(body(T`Ориентировочный срок: 5–10 рабочих дней, из них активные работы — 2–3 дня, остальное — согласования и выдача доступов.`));
children.push(makeTable(
  [900, 4500, 1900, 1700],
  [T`Шаг`, T`Содержание`, T`Владелец`, T`Готовность`],
  [
    [T`1`, T`Заявки в ИБ и ИТ: сервер, сетевые доступы, сервисные учётки`, T`PM`, T`Доступы выданы`],
    [T`2`, T`Подготовка сервера: Python 3.11+, git, пользователь сервиса, NTP`, T`ИТ`, T`SSH-доступ есть`],
    [T`3`, T`Установка: git clone → venv → pip install -r requirements.txt`, T`Администратор`, T`Импорт модулей OK`],
    [T`4`, T`Конфигурация .env: токен бота, ADMIN_TG_IDS, TZ`, T`Администратор`, T`Бот отвечает на /start`],
    [T`5`, T`Прогон тестов на сервере: tests/test_*.py (62 проверки)`, T`Администратор`, T`Все зелёные`],
    [T`6`, T`systemd unit, автоперезапуск, проверка переживания ребута`, T`ИТ`, T`Сервис в autostart`],
    [T`7`, T`Почта: healthcheck отправки/приёма на тестовый ящик`, T`Администратор`, T`Письмо доставлено`],
    [T`8`, T`Календарь: healthcheck CalDAV, тестовое событие`, T`Администратор`, T`Событие в календаре`],
    [T`9`, T`LLM: healthcheck YandexGPT`, T`Администратор`, T`OK от модели`],
    [T`10`, T`Бэкап БД (cron), тест восстановления из копии`, T`ИТ`, T`Восстановление проверено`],
    [T`11`, T`Онбординг пилотной команды: регистрация, проект, роли`, T`PM`, T`Команда в боте`],
    [T`12`, T`Go / No-Go по чек-листу (раздел 11) → старт пилота`, T`PM + ИБ`, T`Пилот запущен`],
  ],
));

// ---------- 8 ----------
children.push(h1(T`8. Эксплуатация: бэкапы, мониторинг, обновления`));
children.push(h2(T`8.1 Резервное копирование`));
children.push(bullet(T`Ежедневная копия файла БД (cron, ночью): pm_assistant.db → каталог бэкапов, хранение 30 дней.`));
children.push(bullet(T`Раз в квартал — тест восстановления: поднять копию, проверить целостность данных.`));
children.push(h2(T`8.2 Мониторинг`));
children.push(bullet(T`Живость процесса: systemd (Restart=always) + внешний пинг (healthcheck-скрипт раз в 5 минут, алерт администратору при падении).`));
children.push(bullet(T`Ошибки модулей: записи calendar_error / mail_error / llm_fallback в audit_log — ежедневный просмотр в пилоте, далее алерт при росте.`));
children.push(bullet(T`Логи: journald, ротация по умолчанию; уровень INFO.`));
children.push(h2(T`8.3 Обновления`));
children.push(bullet(T`Порядок: правки в dev → тесты зелёные → git pull на сервере → pip install при изменении requirements → systemctl restart → смоук-проверка (/digest PM).`));
children.push(bullet(T`Откат: git checkout предыдущего тега + restart; БД обратно совместима (миграций в MVP нет).`));
children.push(bullet(T`Окно обновлений — вне рабочего времени команды; о простое (< 5 мин) агент не уведомляет, пропущенные напоминания дошлются после старта.`));

// ---------- 9 ----------
children.push(h1(T`9. План пилота и критерии успеха`));
children.push(body(T`Пилот: 2 недели, 1–2 реальных проекта, 5–10 исполнителей, 1 PM. Цель — подтвердить ценность и собрать обратную связь перед расширением.`));
children.push(h2(T`9.1 Ход пилота`));
children.push(bullet(T`День 1: онбординг команды (30 минут): регистрация, правила (ответы на запросы, /status), ожидания.`));
children.push(bullet(T`Неделя 1: все задачи пилотных проектов заведены в агента; PM работает через дайджест; ежедневный сбор замечаний.`));
children.push(bullet(T`Неделя 2: включены все каналы (почта, календарь, LLM); недельный отчёт формируется агентом, PM только проверяет.`));
children.push(bullet(T`День 10: ретроспектива, замеры метрик, решение о расширении.`));
children.push(h2(T`9.2 Метрики успеха`));
children.push(makeTable(
  [3800, 2600, 2600],
  [T`Метрика`, T`Цель`, T`Как измерить`],
  [
    [T`Задачи пилотных проектов в агенте`, T`≥ 90%`, T`сверка с планом проекта`],
    [T`Ответы исполнителей на запросы статуса`, T`≥ 80% в день запроса`, T`status_updates / запросы`],
    [T`Доставка напоминаний`, T`≥ 99%`, T`reminders_log vs ошибки`],
    [T`Дайджест PM`, T`ежедневно, без сбоев`, T`audit_log`],
    [T`Время PM на рутину (сбор статусов, отчёты)`, T`−50% к baseline`, T`самооценка PM до/после`],
    [T`Удовлетворённость команды`, T`≥ 7/10`, T`опрос в конце пилота`],
  ],
));
children.push(h2(T`9.3 Критерии выхода из пилота`));
children.push(bullet(T`Метрики достигнуты или понятен план их достижения;`));
children.push(bullet(T`нет критичных инцидентов безопасности и потери данных;`));
children.push(bullet(T`PM подтверждает готовность использовать агента на всех проектах.`));

// ---------- 10 ----------
children.push(h1(T`10. Риски и митигация`));
children.push(makeTable(
  [3600, 5400],
  [T`Риск`, T`Митигация`],
  [
    [T`Доступ к Telegram ограничен политикой ИБ`, T`Согласовать заранее (шаг 1); запасной вариант — только e-mail-канал (уже поддержан), мессенджер-адаптер — отдельная доработка`],
    [T`Задержки согласований ИБ/ИТ`, T`Запустить заявки в день 0; пилот возможен в деградированном режиме (без LLM/почты/календаря)`],
    [T`Команда игнорирует бота`, T`Онбординг, правило «статус = в агенте», PM не принимает статусы в личке; дайджест формируется только из агента`],
    [T`Ошибки LLM при разборе ответов`, T`Нераспознанное уходит PM (FR-13); в пилоте — ручная сверка первой недели`],
    [T`Компрометация токена/секретов`, T`Хранение в .env (600), ротация, отзыв токена у BotFather`],
    [T`Потеря БД`, T`Ежедневный бэкап + тест восстановления; RPO 24 ч, восстановление < 1 ч`],
  ],
));

// ---------- 11 ----------
children.push(h1(T`11. Чек-лист готовности (Go / No-Go)`));
children.push(makeTable(
  [700, 6300, 2000],
  [T`№`, T`Проверка`, T`Статус`],
  [
    [T`1`, T`Согласование ИБ получено (данные, LLM, Telegram)`, T`☐`],
    [T`2`, T`Сервер готов, сетевые доступы открыты (раздел 5)`, T`☐`],
    [T`3`, T`Все секреты выданы и внесены в .env (права 600)`, T`☐`],
    [T`4`, T`62 теста зелёные на сервере`, T`☐`],
    [T`5`, T`systemd: сервис переживает перезагрузку`, T`☐`],
    [T`6`, T`Healthcheck почты, календаря, LLM — OK`, T`☐`],
    [T`7`, T`Бэкап настроен, восстановление проверено`, T`☐`],
    [T`8`, T`Пилотная команда зарегистрирована, проект создан`, T`☐`],
    [T`9`, T`Тестовая задача прошла полный цикл: создание → напоминание → статус → дайджест → отчёт`, T`☐`],
    [T`10`, T`Назначены владелец сервиса и дежурный контакт`, T`☐`],
  ],
));

// ---------- Приложение ----------
children.push(h1(T`Приложение А. Пример systemd unit`));
children.push(body(T`Файл /etc/systemd/system/pm-assistant.service:`));
children.push(code(T`[Unit]`));
children.push(code(T`Description=PM Assistant MVP`));
children.push(code(T`After=network-online.target`));
children.push(code(T`Wants=network-online.target`));
children.push(code(T``));
children.push(code(T`[Service]`));
children.push(code(T`Type=simple`));
children.push(code(T`User=pm-assistant`));
children.push(code(T`WorkingDirectory=/opt/pm-assistant`));
children.push(code(T`EnvironmentFile=/opt/pm-assistant/.env`));
children.push(code(T`ExecStart=/opt/pm-assistant/.venv/bin/python /opt/pm-assistant/main.py`));
children.push(code(T`Restart=always`));
children.push(code(T`RestartSec=10`));
children.push(code(T``));
children.push(code(T`[Install]`));
children.push(code(T`WantedBy=multi-user.target`));
children.push(para(run(T`Команды: sudo systemctl enable --now pm-assistant · журнал: journalctl -u pm-assistant -f`, { italics: true, color: palette.light })));

const doc = new Document({
  features: { updateFields: true },
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: convertInchesToTwip(0.5), hanging: convertInchesToTwip(0.25) } } },
      }],
    }],
  },
  sections: [{
    properties: { page: { margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    headers: {
      default: new Header({
        children: [para(run(T`План развёртывания · MVP «Ассистент PM»`, { size: 18, color: palette.light }), {
          alignment: AlignmentType.RIGHT, spacing: { after: 80 },
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [para(new TextRun({ children: [PageNumber.CURRENT], font, size: 20 }), {
          alignment: AlignmentType.CENTER,
        })],
      }),
    },
    children,
  }],
});

fs.writeFileSync(outputPath, await Packer.toBuffer(doc));
console.log("written:", outputPath);
