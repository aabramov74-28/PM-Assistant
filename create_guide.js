import fs from "node:fs";
import {
  AlignmentType, Document, Footer, Header, HeadingLevel, LevelFormat,
  Packer, PageNumber, Paragraph, ShadingType, Table, TableCell, TableRow,
  TextRun, WidthType, convertInchesToTwip,
} from "docx";

const outputPath = process.argv[2];
if (!outputPath) throw new Error("Usage: node create_guide.js /abs/output.docx");

const T = String.raw;
const palette = { dark: "263238", primary: "37474F", light: "78909C", fill: "EEF3F6", accent: "E8F0E9" };
const font = { ascii: "Calibri", hAnsi: "Calibri", cs: "Calibri", eastAsia: "SimSun" };
const mono = { ascii: "Courier New", hAnsi: "Courier New", cs: "Courier New", eastAsia: "SimSun" };

const run = (text, options = {}) => new TextRun({ text, font, size: 21, ...options });
const para = (children, options = {}) => new Paragraph({
  spacing: { after: 100, line: 264 }, ...options,
  children: Array.isArray(children) ? children : [children],
});
const h1 = (text) => para(run(text, { bold: true, size: 26, color: palette.dark }), {
  spacing: { before: 140, after: 80 },
});
const bullet = (children, options = {}) => para(
  Array.isArray(children) ? children : run(children), {
    numbering: { reference: "bullets", level: 0 }, spacing: { after: 60, line: 264 }, ...options,
  });
const cmd = (text) => new TextRun({ text, font: mono, size: 20, color: "1A4D6E" });

const cell = (children, options = {}) => new TableCell({
  children: [para(Array.isArray(children) ? children : run(children),
                  { spacing: { after: 30, line: 250 } })],
  margins: { top: 80, bottom: 80, left: 120, right: 120 },
  ...options,
});

const children = [];

// ---------- Заголовок ----------
children.push(
  para(run(T`Ассистент PM — памятка для пилотной команды`, { bold: true, size: 34, color: palette.dark }), {
    alignment: AlignmentType.CENTER, spacing: { after: 80 },
  }),
  para(run(T`Бот следит за сроками, собирает статусы и делает отчёты за вас. Одна страница — всё, что нужно знать.`,
           { size: 20, color: palette.light }), {
    alignment: AlignmentType.CENTER, spacing: { after: 140 },
  }),
);

// ---------- Старт ----------
children.push(h1(T`1. Первый запуск (1 минута)`));
children.push(bullet([run(T`Найдите бота в Telegram и отправьте `), cmd("/start"), run(T`.`)]));
children.push(bullet(T`Введите имя и фамилию, корпоративный e-mail, выберите роль кнопкой.`));
children.push(bullet([run(T`Готово — команда `), cmd("/help"), run(T` покажет все возможности.`)]));

// ---------- Исполнителям ----------
children.push(h1(T`2. Исполнителям`));
children.push(para(run(T`Бот сам напомнит о задаче: за 2 дня и за 1 день до срока, а в день дедлайна попросит статус. Отвечать можно двумя способами:`, {})));
children.push(bullet([run(T`Кнопки под запросом`, { bold: true }), run(T` — «Готово», «В работе», «Блокер». Один тап, ничего печатать не надо.`)]));
children.push(bullet([run(T`Свободный текст`, { bold: true }), run(T` — команда `), cmd("/status TASK-NNN"), run(T` и пара слов. Бот поймёт обычный русский:`)]));
children.push(para(run(T`«/status TASK-014 почти закончил, процентов 80, завтра отдам на проверку»`, { italics: true, color: palette.light }), {
  indent: { left: convertInchesToTwip(0.5) }, shading: { type: ShadingType.CLEAR, fill: "F5F7F8" }, spacing: { after: 60 },
}));
children.push(para(run(T`«/status TASK-014 заблокирована — жду доступ к тестовому стенду от ИТ»`, { italics: true, color: palette.light }), {
  indent: { left: convertInchesToTwip(0.5) }, shading: { type: ShadingType.CLEAR, fill: "F5F7F8" },
}));

children.push(makeTableRow());

function makeTableRow() {
  const widths = [3000, 6000];
  return new Table({
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ children: [
        cell(T`Команда`, { shading: { type: ShadingType.CLEAR, fill: palette.fill }, width: { size: widths[0], type: WidthType.DXA } }),
        cell(T`Зачем`, { shading: { type: ShadingType.CLEAR, fill: palette.fill }, width: { size: widths[1], type: WidthType.DXA } }),
      ] }),
      ...[
        [T`/mytasks`, T`мои активные задачи с дедлайнами`],
        [T`/status TASK-NNN текст`, T`обновить статус (статус, %, комментарий)`],
        [T`/done TASK-NNN`, T`задача готова → уходит на проверку PM`],
        [T`/extend TASK-NNN ДД.ММ.ГГГГ причина`, T`запросить перенос срока — PM подтвердит кнопкой`],
      ].map(([c, d]) => new TableRow({ children: [
        cell([cmd(c)], { width: { size: widths[0], type: WidthType.DXA } }),
        cell(d, { width: { size: widths[1], type: WidthType.DXA } }),
      ] })),
    ],
  });
}
children.push(para(run(T``, {}), { spacing: { after: 0 } }));

// ---------- PM ----------
children.push(h1(T`3. Проектному менеджеру`));
{
  const widths = [3000, 6000];
  children.push(new Table({
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ children: [
        cell(T`Команда`, { shading: { type: ShadingType.CLEAR, fill: palette.fill }, width: { size: widths[0], type: WidthType.DXA } }),
        cell(T`Зачем`, { shading: { type: ShadingType.CLEAR, fill: palette.fill }, width: { size: widths[1], type: WidthType.DXA } }),
      ] }),
      ...[
        [T`/newproject CODE Название`, T`создать проект`],
        [T`/newtask`, T`мастер постановки задачи: проект → название → исполнитель → дедлайн`],
        [T`/tasks`, T`все активные задачи портфеля`],
        [T`/digest`, T`дайджест прямо сейчас (иначе — каждый день в 9:00)`],
        [T`/report`, T`статус-отчёт .docx за неделю (автоматически — пт, 17:00)`],
      ].map(([c, d]) => new TableRow({ children: [
        cell([cmd(c)], { width: { size: widths[0], type: WidthType.DXA } }),
        cell(d, { width: { size: widths[1], type: WidthType.DXA } }),
      ] })),
    ],
  }));
}

// ---------- Правила ----------
children.push(h1(T`4. Три правила пилота`));
children.push(bullet([run(T`Статус живёт в боте. `, { bold: true }), run(T`PM не принимает статусы в личке и на встречах — только через бота.`)]));
children.push(bullet([run(T`Отвечаем в день запроса. `, { bold: true }), run(T`Вечером (18:00) бот спросит об активных задачах — один тап по кнопке.`)]));
children.push(bullet([run(T`Перенос срока — через /extend. `, { bold: true }), run(T`Просрочка без запроса — это эскалация к PM на 2-й день, автоматически.`)]));
children.push(para(run(T`Вопросы и замечания по боту — в чат пилота или администратору. Спасибо, что помогаете сделать его лучше!`, { italics: true, color: palette.light }), { spacing: { before: 120 } }));

const doc = new Document({
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: convertInchesToTwip(0.45), hanging: convertInchesToTwip(0.22) } } },
      }],
    }],
  },
  sections: [{
    properties: { page: { margin: { top: 1000, bottom: 1000, left: 1200, right: 1200 } } },
    footers: {
      default: new Footer({
        children: [para(run(T`Ассистент PM · пилот · ноябрь 2026`, { size: 16, color: palette.light }), {
          alignment: AlignmentType.CENTER, spacing: { after: 0 },
        })],
      }),
    },
    children,
  }],
});

fs.writeFileSync(outputPath, await Packer.toBuffer(doc));
console.log("written:", outputPath);
