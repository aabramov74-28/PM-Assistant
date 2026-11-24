import fs from "node:fs";
import path from "node:path";
import {
  AlignmentType,
  Document,
  Footer,
  Header,
  HeadingLevel,
  ImageRun,
  ImportedXmlComponent,
  LevelFormat,
  Packer,
  PageBreak,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
  convertInchesToTwip,
} from "docx";

const outputPath = process.argv[2];
if (!outputPath) throw new Error("Usage: node create.js /abs/output.docx");

const outputDir = path.dirname(outputPath);
const assetDir = path.join(outputDir, "assets");
fs.mkdirSync(assetDir, { recursive: true });

const T = String.raw;

const palette = {
  dark: "263238",
  primary: "37474F",
  light: "78909C",
  border: "D8E0E3",
  fill: "EEF3F6",
};

const font = {
  ascii: "Times New Roman",
  hAnsi: "Times New Roman",
  cs: "Times New Roman",
  eastAsia: "SimSun",
};

const run = (text, options = {}) => new TextRun({ text, font, size: 24, ...options });
const para = (children, options = {}) => new Paragraph({
  spacing: { after: 160, line: 300 },
  ...options,
  children: Array.isArray(children) ? children : [children],
});
const body = (text) => para(run(text), { indent: { firstLine: convertInchesToTwip(0.33) } });
const bodyMix = (runs) => para(runs, { indent: { firstLine: convertInchesToTwip(0.33) } });
const h1 = (text) => para(run(text, { bold: true, size: 30, color: palette.dark }), {
  heading: HeadingLevel.HEADING_1, spacing: { before: 320, after: 140 },
});
const h2 = (text) => para(run(text, { bold: true, size: 26, color: palette.primary }), {
  heading: HeadingLevel.HEADING_2, spacing: { before: 260, after: 120 },
});
const bullet = (text) => para(run(text), {
  numbering: { reference: "bullets", level: 0 }, spacing: { after: 80, line: 300 },
});
const fr = (code, text) => para([run(code + "  ", { bold: true }), run(text)], {
  spacing: { after: 100, line: 300 }, indent: { left: convertInchesToTwip(0.25) },
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
    new TableRow({
      children: header.map((t, i) => cell(t, {
        shading: { type: ShadingType.CLEAR, fill: palette.fill },
        width: { size: widths[i], type: WidthType.DXA },
      })),
    }),
    ...rows.map((r) => new TableRow({
      children: r.map((t, i) => cell(t, { width: { size: widths[i], type: WidthType.DXA } })),
    })),
  ],
});

const xmlEscape = (value) => String(value)
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
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
  { title: T`1. Общие сведения`, level: 1, page: 3 },
  { title: T`2. Термины и сокращения`, level: 1, page: 3 },
  { title: T`3. Область MVP`, level: 1, page: 4 },
  { title: T`4. Пользователи и роли`, level: 1, page: 4 },
  { title: T`5. Функциональные требования`, level: 1, page: 5 },
  { title: T`5.1 Управление задачами (Telegram-бот)`, level: 2, page: 5 },
  { title: T`5.2 Мониторинг сроков и напоминания`, level: 2, page: 6 },
  { title: T`5.3 Сбор обратной связи от исполнителей`, level: 2, page: 7 },
  { title: T`5.4 Отчётность`, level: 2, page: 7 },
  { title: T`5.5 Интеграция с Яндекс 360 Календарь`, level: 2, page: 8 },
  { title: T`5.6 Почтовый модуль`, level: 2, page: 8 },
  { title: T`5.7 LLM-модуль`, level: 2, page: 9 },
  { title: T`6. Сценарии использования`, level: 1, page: 9 },
  { title: T`7. Нефункциональные требования`, level: 1, page: 10 },
  { title: T`8. Архитектура решения`, level: 1, page: 11 },
  { title: T`9. Модель данных`, level: 1, page: 12 },
  { title: T`10. Критерии приёмки`, level: 1, page: 13 },
  { title: T`11. Этапы и план работ`, level: 1, page: 13 },
  { title: T`12. Риски и ограничения`, level: 1, page: 14 },
];

const children = [];

// ---------- Cover ----------
children.push(
  para(run(T`ТЕХНИЧЕСКОЕ ЗАДАНИЕ`, { bold: true, size: 44, color: palette.dark }), {
    alignment: AlignmentType.CENTER, spacing: { before: 2800, after: 240 },
  }),
  para(run(T`MVP ИИ-агента «Ассистент PM»`, { bold: true, size: 32, color: palette.primary }), {
    alignment: AlignmentType.CENTER, spacing: { after: 160 },
  }),
  para(run(T`Координация календаря, Telegram-чатов и почты; контроль сроков задач; обратная связь исполнителей; отчётность`, { size: 24, color: palette.light }), {
    alignment: AlignmentType.CENTER, spacing: { after: 480 },
  }),
  para(run(T`Версия 1.0  ·  23 ноября 2026 г.`, { size: 22, color: palette.light }), {
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

// ---------- 1. Общие сведения ----------
children.push(h1(T`1. Общие сведения`));
children.push(h2(T`1.1 Наименование системы`));
children.push(body(T`Автоматизированная система «Ассистент PM» (далее — Агент) — минимально жизнеспособная версия (MVP) ИИ-агента, выполняющего функции координатора проектного офиса: ведение задач, контроль сроков исполнения, сбор обратной связи от исполнителей и подготовка отчётности.`));
children.push(h2(T`1.2 Область применения`));
children.push(body(T`Проектный офис, ведущий портфель проектов по разработке финтех- и финансовых продуктов. Агент обслуживает проектные команды, работающие в Telegram-чатах, корпоративной почте и Яндекс 360 Календаре.`));
children.push(h2(T`1.3 Цели создания`));
children.push(bullet(T`снижение операционной нагрузки на проектных менеджеров (PM): ручной контроль сроков, обзвоны и напоминания, сбор статусов, подготовка регулярной отчётности;`));
children.push(bullet(T`повышение дисциплины исполнения задач за счёт систематических напоминаний и прозрачной эскалации просрочек;`));
children.push(bullet(T`единая точка контроля сроков по всем проектам портфеля;`));
children.push(bullet(T`автоматизация ежедневной и еженедельной отчётности без ручного заполнения.`));
children.push(h2(T`1.4 Принцип работы`));
children.push(body(T`Агент не заменяет PM, а снимает с него рутинные операции. Все критичные действия (сдвиг сроков, эскалация руководству, отправка внешних отчётов) выполняются по подтверждению PM (принцип human-in-the-loop).`));

// ---------- 2. Термины ----------
children.push(h1(T`2. Термины и сокращения`));
children.push(makeTable(
  [2200, 6800],
  [T`Термин`, T`Определение`],
  [
    [T`PM`, T`Проектный менеджер — владелец проекта, основной пользователь Агента`],
    [T`Исполнитель`, T`Участник проектной команды, ответственный за задачи`],
    [T`Дайджест`, T`Ежедневная сводка для PM: события за день, просрочки, ближайшие дедлайны`],
    [T`Эскалация`, T`Автоматическое уведомление более высокого уровня при нарушении сроков`],
    [T`LLM`, T`Большая языковая модель, используемая для разбора ответов в свободной форме`],
    [T`CalDAV`, T`Протокол доступа к календарям Яндекс 360`],
    [T`IMAP / SMTP`, T`Протоколы чтения и отправки корпоративной почты`],
    [T`Human-in-the-loop`, T`Режим, при котором критичное действие исполняется только после подтверждения человеком`],
  ],
));

// ---------- 3. Область MVP ----------
children.push(h1(T`3. Область MVP`));
children.push(h2(T`3.1 Входит в MVP`));
children.push(bullet(T`ведение задач проектов через Telegram-бота: создание, назначение исполнителей, статусы, дедлайны;`));
children.push(bullet(T`автоматический мониторинг сроков: напоминания исполнителям и эскалации PM по матрице правил;`));
children.push(bullet(T`сбор обратной связи от исполнителей в Telegram и по e-mail (статус, прогресс, блокеры);`));
children.push(bullet(T`ежедневный дайджест для PM (Telegram и/или e-mail);`));
children.push(bullet(T`еженедельный статус-отчёт (документ .docx) с отправкой по e-mail;`));
children.push(bullet(T`синхронизация дедлайнов задач с Яндекс 360 Календарь (CalDAV);`));
children.push(bullet(T`журналирование всех действий Агента (аудит).`));
children.push(h2(T`3.2 Не входит в MVP (этапы 2+)`));
children.push(bullet(T`транскрибация встреч и автоматическая генерация протоколов;`));
children.push(bullet(T`интеграция с Jira / Kaiten / Notion и прочими трекерами;`));
children.push(bullet(T`база знаний проектов и поиск по документации;`));
children.push(bullet(T`веб-интерфейс и дашборды портфеля;`));
children.push(bullet(T`управление рисками, бюджетом и ресурсной загрузкой.`));

// ---------- 4. Роли ----------
children.push(h1(T`4. Пользователи и роли`));
children.push(makeTable(
  [2000, 4100, 2900],
  [T`Роль`, T`Возможности`, T`Каналы взаимодействия`],
  [
    [T`PM`, T`Создание и редактирование задач, назначение исполнителей, подтверждение эскалаций, получение дайджестов и отчётов, запрос отчёта в любой момент`, T`Telegram, e-mail`],
    [T`Исполнитель`, T`Просмотр своих задач, обновление статуса и прогресса, ответы на запросы Агента, запрос переноса срока`, T`Telegram, e-mail`],
    [T`Администратор`, T`Управление пользователями и проектами, настройка расписаний и матрицы эскалации, доступ к журналу аудита`, T`Конфигурационные файлы, Telegram`],
  ],
));

// ---------- 5. Функциональные требования ----------
children.push(h1(T`5. Функциональные требования`));

children.push(h2(T`5.1 Управление задачами (Telegram-бот)`));
children.push(body(T`Основной интерфейс Агента — Telegram-бот. Личные чаты используются для уведомлений и сбора статусов; групповые проектные чаты — для постановки задач и сводок.`));
children.push(fr(T`FR-01.`, T`Регистрация пользователя по команде /start: Агент связывает Telegram-аккаунт с карточкой сотрудника (имя, e-mail, роль, проекты).`));
children.push(fr(T`FR-02.`, T`Создание задачи командой /newtask в режиме мастера: название, проект, исполнитель (выбор из команды), дедлайн, описание, приоритет.`));
children.push(fr(T`FR-03.`, T`Каждой задаче присваивается уникальный идентификатор вида TASK-NNN, используемый во всех уведомлениях, письмах и отчётах.`));
children.push(fr(T`FR-04.`, T`Жизненный цикл задачи: Новая → В работе → На проверке → Выполнена; дополнительный статус Заблокирована с обязательным комментарием о причине.`));
children.push(fr(T`FR-05.`, T`Просмотр задач: /mytasks — задачи исполнителя; /tasks — задачи проекта или портфеля (для PM) с фильтрами по статусу и сроку.`));
children.push(fr(T`FR-06.`, T`Изменение дедлайна — только PM или по подтверждению PM: исполнитель запрашивает перенос с обоснованием, PM подтверждает кнопкой в чате.`));
children.push(fr(T`FR-07.`, T`Все изменения задачи (создание, смена статуса, перенос срока) фиксируются в журнале с указанием автора и времени.`));
children.push(para(run(T`Команды бота:`, { bold: true }), { spacing: { before: 160, after: 100 } }));
children.push(makeTable(
  [1900, 4900, 2200],
  [T`Команда`, T`Действие`, T`Кому доступна`],
  [
    [T`/start`, T`Регистрация и привязка аккаунта`, T`Все`],
    [T`/newtask`, T`Мастер создания задачи`, T`PM`],
    [T`/mytasks`, T`Список моих активных задач`, T`Все`],
    [T`/tasks`, T`Задачи проекта / портфеля с фильтрами`, T`PM`],
    [T`/done TASK-NNN`, T`Отметить задачу выполненной`, T`Исполнитель, PM`],
    [T`/status TASK-NNN`, T`Обновить статус, прогресс, комментарий`, T`Исполнитель`],
    [T`/digest`, T`Получить дайджест немедленно`, T`PM`],
    [T`/report`, T`Сформировать статус-отчёт по запросу`, T`PM`],
  ],
));

children.push(h2(T`5.2 Мониторинг сроков и напоминания`));
children.push(body(T`Планировщик Агента ежедневно проверяет сроки всех активных задач и инициирует напоминания и эскалации по матрице правил. Время работы планировщика и часовой пояс (Europe/Moscow) настраиваются администратором.`));
children.push(fr(T`FR-08.`, T`Напоминания исполнителю отправляются в Telegram; при отсутствии реакции в течение рабочего дня — дублируются по e-mail.`));
children.push(fr(T`FR-09.`, T`Запрос статуса в день дедлайна содержит кнопки быстрых ответов: «Готово», «В работе, успеваю», «Нужен перенос», «Заблокирована».`));
children.push(fr(T`FR-10.`, T`Эскалации выполняются по матрице, приведённой ниже; эскалация уровня 3 и выше включается в дайджест PM автоматически.`));
children.push(fr(T`FR-11.`, T`Задача без обновления статуса более 3 рабочих дней помечается «зависшей» и попадает в дайджест PM.`));
children.push(para(run(T`Матрица напоминаний и эскалаций:`, { bold: true }), { spacing: { before: 160, after: 100 } }));
children.push(makeTable(
  [2800, 3400, 2800],
  [T`Событие`, T`Действие Агента`, T`Получатель`],
  [
    [T`2 дня до дедлайна`, T`Напоминание о приближении срока`, T`Исполнитель`],
    [T`1 день до дедлайна`, T`Напоминание + запрос подтверждения готовности`, T`Исполнитель`],
    [T`День дедлайна`, T`Запрос статуса с кнопками быстрых ответов`, T`Исполнитель`],
    [T`Просрочка 1 день`, T`Уведомление о просрочке, предложение запросить перенос`, T`Исполнитель`],
    [T`Просрочка 2 дня`, T`Уведомление о просрочке задачи с контекстом`, T`PM`],
    [T`Просрочка 3+ дня`, T`Эскалация: задача помечается «риск», включается в дайджест`, T`PM (дайджест)`],
  ],
));

children.push(h2(T`5.3 Сбор обратной связи от исполнителей`));
children.push(fr(T`FR-12.`, T`В конце каждого рабочего дня Агент опрашивает исполнителей, у которых есть активные задачи: статус, процент готовности, блокеры. Ответ — кнопками и/или свободным текстом.`));
children.push(fr(T`FR-13.`, T`Ответы в свободной форме разбираются LLM-модулем и преобразуются в структурированное обновление задачи; неуверенно распознанные ответы отправляются PM на разбор.`));
children.push(fr(T`FR-14.`, T`Исполнители без Telegram могут отвечать по e-mail: письмо-запрос содержит в теме тег [TASK-NNN], ответ автоматически привязывается к задаче.`));
children.push(fr(T`FR-15.`, T`Все полученные статусы аккумулируются и используются в дайджесте и недельном отчёте без дополнительных запросов.`));

children.push(h2(T`5.4 Отчётность`));
children.push(fr(T`FR-16.`, T`Ежедневный дайджест (по умолчанию 9:00): события за прошедший день, просроченные задачи, дедлайны ближайших 3 дней, зависшие задачи, эскалации. Доставка — в Telegram PM, опционально на e-mail.`));
children.push(fr(T`FR-17.`, T`Еженедельный статус-отчёт (пятница, 17:00): документ .docx по всем проектам — выполнено за неделю, в работе, просрочено, блокеры по словам исполнителей, риски. Отправка PM на e-mail; внешняя рассылка — только после подтверждения PM.`));
children.push(fr(T`FR-18.`, T`Отчёт по запросу /report: PM выбирает проект и период, Агент формирует отчёт в течение 1 минуты.`));
children.push(fr(T`FR-19.`, T`Все факты в отчётах берутся только из базы данных Агента; LLM используется исключительно для формулировок и не может изменять данные.`));

children.push(h2(T`5.5 Интеграция с Яндекс 360 Календарь`));
children.push(fr(T`FR-20.`, T`Подключение по протоколу CalDAV с использованием пароля приложения; на каждый проект выделяется отдельный календарь.`));
children.push(fr(T`FR-21.`, T`При создании задачи Агент создаёт событие-дедлайн в календаре проекта (название задачи, идентификатор, исполнитель).`));
children.push(fr(T`FR-22.`, T`При переносе срока событие обновляется; при отмене задачи — удаляется. Статус синхронизации отображается в карточке задачи.`));
children.push(fr(T`FR-23.`, T`При недоступности CalDAV синхронизация откладывается с повторными попытками; сбой фиксируется в журнале и сообщается администратору.`));

children.push(h2(T`5.6 Почтовый модуль`));
children.push(fr(T`FR-24.`, T`Отправка по SMTP (TLS): дайджесты, еженедельные отчёты, напоминания исполнителям без Telegram.`));
children.push(fr(T`FR-25.`, T`Чтение входящих по IMAP: Агент обрабатывает ответы на свои письма, сопоставляет их с задачами по тегу [TASK-NNN] в теме и преобразует в обновления статуса.`));
children.push(fr(T`FR-26.`, T`Письма, которые не удалось сопоставить или разобрать, пересылаются PM с пометкой «требует внимания»; Агент не удаляет входящие письма.`));

children.push(h2(T`5.7 LLM-модуль`));
children.push(fr(T`FR-27.`, T`LLM применяется для двух задач: разбор ответов исполнителей в свободной форме и генерация связных формулировок в отчётах на основе структурированных данных.`));
children.push(fr(T`FR-28.`, T`Подключение через OpenAI-совместимый API; конкретный провайдер (внешний сервис или модель в контуре заказчика) определяется требованиями ИБ и выносится в конфигурацию.`));
children.push(fr(T`FR-29.`, T`При недоступности LLM Агент продолжает работу в деградированном режиме: ответы принимаются только кнопками, отчёты строятся по шаблонам.`));

// ---------- 6. Сценарии ----------
children.push(h1(T`6. Сценарии использования`));
const scenario = (title, steps) => {
  children.push(para(run(title, { bold: true, color: palette.primary }), { spacing: { before: 180, after: 100 } }));
  steps.forEach((s, i) => children.push(para(run(`${i + 1}. ${s}`), {
    indent: { left: convertInchesToTwip(0.25) }, spacing: { after: 60, line: 300 },
  })));
};
scenario(T`Сценарий 1. Постановка задачи`, [
  T`PM в проектном чате вводит /newtask.`,
  T`Агент проводит по шагам мастера: название, исполнитель, дедлайн, описание.`,
  T`Задача создана: исполнитель получает личное уведомление, в календаре проекта появляется событие-дедлайн.`,
]);
scenario(T`Сценарий 2. Штатное исполнение`, [
  T`За 2 дня и за 1 день до срока исполнитель получает напоминания.`,
  T`В день дедлайна Агент запрашивает статус; исполнитель нажимает «Готово».`,
  T`Задача переходит в статус «На проверке», PM получает уведомление и подтверждает закрытие.`,
]);
scenario(T`Сценарий 3. Просрочка и эскалация`, [
  T`Дедлайн прошёл, статус не обновлён: исполнитель получает уведомление о просрочке.`,
  T`На второй день просрочки PM получает уведомление с контекстом задачи.`,
  T`На третий день задача помечается «риск» и попадает в дайджест; PM решает: перенести срок, сменить исполнителя или эскалировать руководству.`,
]);
scenario(T`Сценарий 4. Утренний дайджест`, [
  T`В 9:00 PM получает дайджест: что закрыто вчера, что просрочено, что горит в ближайшие 3 дня.`,
  T`PM по ссылке-идентификатору открывает нужную задачу и при необходимости действует прямо из чата.`,
]);
scenario(T`Сценарий 5. Недельный отчёт`, [
  T`В пятницу в 17:00 Агент формирует статус-отчёт .docx по всем проектам и отправляет PM на почту.`,
  T`PM проверяет отчёт и одной кнопкой подтверждает рассылку руководству.`,
]);

// ---------- 7. НФТ ----------
children.push(h1(T`7. Нефункциональные требования`));
children.push(h2(T`7.1 Безопасность`));
children.push(bullet(T`токены и пароли (Telegram, CalDAV, SMTP/IMAP, LLM API) хранятся только в конфигурационных файлах с ограниченным доступом, не в коде;`));
children.push(bullet(T`все внешние подключения — по TLS; размещение Агента — на сервере в контуре заказчика;`));
children.push(bullet(T`журнал аудита: каждое действие Агента и пользователя фиксируется с меткой времени;`));
children.push(bullet(T`персональные данные ограничиваются минимумом: имя, e-mail, Telegram ID.`));
children.push(h2(T`7.2 Производительность и надёжность`));
children.push(bullet(T`нагрузка MVP: до 50 пользователей, до 500 активных задач;`));
children.push(bullet(T`время ответа бота на команду — не более 3 секунд; формирование отчёта — не более 1 минуты;`));
children.push(bullet(T`автоматический перезапуск после сбоя; состояние полностью сохраняется в базе данных;`));
children.push(bullet(T`пропущенные из-за простоя напоминания отправляются при восстановлении с пометкой о задержке.`));
children.push(h2(T`7.3 Эксплуатация`));
children.push(bullet(T`язык интерфейса и отчётов — русский; часовой пояс по умолчанию Europe/Moscow;`));
children.push(bullet(T`развёртывание — один сервис (Python) с базой SQLite, запуск как системная служба;`));
children.push(bullet(T`резервное копирование базы данных — ежедневно.`));

// ---------- 8. Архитектура ----------
children.push(h1(T`8. Архитектура решения`));
children.push(body(T`Агент реализуется как единый сервис на Python 3.11+: Telegram-бот (python-telegram-bot), планировщик (APScheduler), модули интеграций (caldav для Яндекс 360, imaplib/smtplib для почты), генератор отчётов (docx) и LLM-модуль (OpenAI-совместимый API). Данные хранятся в SQLite. Структура модульная: каналы и интеграции изолированы от ядра, что позволяет на этапе 2 добавлять новые трекеры и каналы без переработки системы.`));
const archPath = path.join(assetDir, "architecture.png");
if (fs.existsSync(archPath)) {
  children.push(para(new ImageRun({
    type: "png",
    data: fs.readFileSync(archPath),
    transformation: { width: 560, height: 310 },
  }), { alignment: AlignmentType.CENTER, spacing: { before: 160, after: 80 } }));
  children.push(para(run(T`Рис. 1. Архитектура MVP «Ассистент PM»`, { italics: true, color: palette.light, size: 20 }), { alignment: AlignmentType.CENTER }));
}

// ---------- 9. Модель данных ----------
children.push(h1(T`9. Модель данных`));
children.push(body(T`Хранилище MVP — SQLite. Основные сущности:`));
children.push(makeTable(
  [2000, 3500, 3500],
  [T`Таблица`, T`Назначение`, T`Ключевые поля`],
  [
    [T`users`, T`Сотрудники и роли`, T`id, имя, e-mail, telegram_id, роль`],
    [T`projects`, T`Проекты портфеля`, T`id, название, код, caldav_calendar_id`],
    [T`tasks`, T`Задачи`, T`id (TASK-NNN), проект, название, описание, исполнитель, автор, дедлайн, статус, приоритет, calendar_event_id`],
    [T`status_updates`, T`История обновлений и обратная связь`, T`id, задача, автор, статус, прогресс %, комментарий, канал (TG/e-mail)`],
    [T`reminders_log`, T`Журнал напоминаний и эскалаций`, T`id, задача, тип события, канал, время отправки`],
    [T`reports_log`, T`Журнал сформированных отчётов`, T`id, тип, период, файл, время отправки`],
  ],
));

// ---------- 10. Критерии приёмки ----------
children.push(h1(T`10. Критерии приёмки`));
children.push(makeTable(
  [700, 5000, 3300],
  [T`№`, T`Критерий`, T`Способ проверки`],
  [
    [T`1`, T`PM создаёт задачу через бота за ≤ 2 минут; исполнитель получает уведомление и событие в календаре`, T`Тест сценария 1`],
    [T`2`, T`Напоминания и эскалации срабатывают в срок по матрице (раздел 5.2)`, T`Тест на контрольных датах`],
    [T`3`, T`Ответ исполнителя кнопкой или свободным текстом корректно обновляет статус задачи`, T`Тест сценария 2`],
    [T`4`, T`Ответ по e-mail с тегом [TASK-NNN] привязывается к задаче`, T`Тест почтового модуля`],
    [T`5`, T`Дайджест приходит PM в заданное время и содержит все просрочки и дедлайны`, T`Контроль 5 рабочих дней`],
    [T`6`, T`Еженедельный отчёт .docx формируется и отправляется на e-mail`, T`Тест сценария 5`],
    [T`7`, T`При отключённом LLM система работает в деградированном режиме без ошибок`, T`Тест отказа`],
    [T`8`, T`Все действия фиксируются в журнале аудита`, T`Просмотр журнала`],
  ],
));

// ---------- 11. План ----------
children.push(h1(T`11. Этапы и план работ`));
children.push(makeTable(
  [1500, 4600, 2900],
  [T`Этап`, T`Содержание`, T`Результат`],
  [
    [T`Неделя 1`, T`Каркас сервиса, база данных, регистрация пользователей, команды управления задачами`, T`Работающий бот с задачами`],
    [T`Неделя 2`, T`Планировщик, матрица напоминаний и эскалаций, уведомления`, T`Контроль сроков`],
    [T`Неделя 3`, T`Сбор обратной связи: кнопки, свободный текст, LLM-разбор, e-mail-ответы`, T`Обратная связь исполнителей`],
    [T`Неделя 4`, T`Интеграции: Яндекс 360 Календарь (CalDAV), корпоративная почта (IMAP/SMTP)`, T`Календарь и почта подключены`],
    [T`Неделя 5`, T`Дайджесты и еженедельный статус-отчёт (.docx)`, T`Автоматическая отчётность`],
    [T`Неделя 6`, T`Пилот на 1–2 проектах, приёмочные испытания, корректировки`, T`Приёмка MVP`],
  ],
));

// ---------- 12. Риски ----------
children.push(h1(T`12. Риски и ограничения`));
children.push(bullet(T`Ошибки LLM при разборе свободного текста — снижаются подтверждением кнопками и передачей неуверенных ответов PM (FR-13, FR-29).`));
children.push(bullet(T`Ограничения CalDAV Яндекс 360 (пароли приложений, лимиты запросов) — выявляются на неделе 4, при необходимости синхронизация делается односторонней (Агент → Календарь).`));
children.push(bullet(T`Зависимость от Telegram как основного канала — компенсируется дублированием критичных уведомлений по e-mail (FR-08).`));
children.push(bullet(T`Принятие командой: если исполнители игнорируют бота, контроль сроков не работает — на пилоте закладывается работа с командой и настройка частоты напоминаний.`));
children.push(bullet(T`Классификация данных: до решения ИБ по LLM-провайдеру в разбор отправляются только тексты статусов, без чувствительного содержания проектов.`));

const doc = new Document({
  features: { updateFields: true },
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{
        level: 0,
        format: LevelFormat.BULLET,
        text: "•",
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: convertInchesToTwip(0.5), hanging: convertInchesToTwip(0.25) } } },
      }],
    }],
  },
  sections: [{
    properties: {
      page: { margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } },
    },
    headers: {
      default: new Header({
        children: [para(run(T`ТЗ · MVP ИИ-агента «Ассистент PM»`, { size: 18, color: palette.light }), {
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
