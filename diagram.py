import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(11.5, 6.4), dpi=200)
ax.set_xlim(0, 100)
ax.set_ylim(0, 62)
ax.axis("off")

DARK = "#263238"
PRIMARY = "#37474F"
LIGHT = "#78909C"
FILL = "#EEF3F6"
ACCENT = "#B0BEC5"


def box(x, y, w, h, text, fc=FILL, ec=PRIMARY, fs=10, bold=True, tc=DARK, lw=1.4):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.6",
                       linewidth=lw, edgecolor=ec, facecolor=fc, zorder=2)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color=tc, fontweight="bold" if bold else "normal",
            linespacing=1.5, zorder=3)


def arrow(x1, y1, x2, y2, style="<|-", color=LIGHT, lw=1.8, ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                 mutation_scale=14, linewidth=lw, color=color,
                 linestyle=ls, zorder=1, shrinkA=2, shrinkB=2))


# Left column: external channels
box(2, 46, 24, 12, "Telegram Bot API\n(чаты команды)")
box(2, 26, 24, 12, "Корпоративная почта\n(IMAP / SMTP)")
box(2, 6, 24, 12, "Яндекс 360 Календарь\n(CalDAV)")

# Center: core
box(33, 2, 34, 58, "", fc="white", ec=PRIMARY, lw=1.8)
ax.text(50, 56.5, "Ядро агента (Python)", ha="center", va="center",
        fontsize=12, fontweight="bold", color=DARK)

box(35, 40.5, 30, 11, "Telegram-бот\nкоманды и диалоги с командой", fs=9)
box(35, 26.5, 30, 11, "Планировщик\nнапоминания и эскалации", fs=9)
box(35, 12.5, 30, 11, "Интеграции\nпочта и календарь", fs=9)
box(35, 4.0, 30, 6.5, "LLM-модуль: разбор ответов", fs=9, fc="#F7F9FA")

# Right column
box(74, 42, 24, 12, "SQLite\nзадачи, статусы, логи")
box(74, 24, 24, 12, "Генератор отчётов\nдайджесты, статус-отчёты")
box(74, 6, 24, 12, "Каналы доставки\nTelegram, e-mail")

# Arrows
arrow(26.5, 52, 32.5, 48, style="<|-")
arrow(26.5, 32, 32.5, 34, style="<|-")
arrow(26.5, 12, 32.5, 16, style="<|-")
arrow(67.5, 45, 73.5, 48, style="<|-")
arrow(67.5, 30, 73.5, 30, style="<|-")
arrow(73.5, 26, 67.5, 12, style="<|-")
arrow(86, 23.5, 86, 18.5, style="-|>")

ax.set_title("Архитектура MVP «Ассистент PM»", fontsize=14, fontweight="bold",
             color=DARK, pad=14)

plt.tight_layout()
plt.savefig("/Users/a3bramov/Documents/Kimi/Workspaces/PM Agent/assets/architecture.png",
            bbox_inches="tight", facecolor="white")
print("saved")
