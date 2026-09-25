---
name: timesheet
description: Учёт времени по двум табелям (client — productsearch, employer — resolventa) — сводка недели против нормы, черновик из активности и ручных записей, запись ворклогов в Jira только после явного «да». Использовать, когда пользователь просит закрыть неделю, посмотреть списанное время или записать ворклоги.
user_invocable: true
arguments:
  - name: week
    description: "Неделя: W39 или 2026-W39; по умолчанию текущая"
    required: false
---

# /timesheet — закрыть неделю

CLI: `~/.claude/skills/timesheet/timesheet` (ставится `install.sh`). Правила табелей —
`~/.config/devflow/timesheet.json` (образец `timesheet.example.json`), состояние —
`~/.claude/devflow/timesheet/` (`manual-<week>.json`, `draft-<week>.json`, журнал `sent.jsonl`).
В Jira CLI ходит только через `integrations/jira-worklog.sh` из репозитория devflow.

## Порядок в сессии

Просмотр в браузере: `timesheet serve [--port 8765]` → `http://127.0.0.1:8765/` — сводка,
черновик, отправленное, переключение недель; пересчёт только кнопкой. В Jira страница не пишет.

1. **Сводка.** `timesheet summary --week W39` — списано/норма по дням в обоих табелях.
2. **Черновик.** `timesheet draft --week W39` — показать пользователю вывод целиком.
3. **Правки словами.** Пользователь говорит, что поменять: ручные строки —
   `timesheet manual add --sheet client --day 2026-09-22 --key SE-12 --hours 2 [--comment …]`,
   `timesheet manual list|rm`; затем снова `draft`. Черновик руками не править.
4. **Dry run.** `timesheet apply --week W39 [--sheet client]` — список того, что уйдёт в каждый
   табель, и пропуски с причиной. Строки с `no-mirror`, `ambiguous-mirror`, `mirror-unavailable`,
   `overflow`, `create-mirror` не пишутся — их закрывают ручной строкой или зеркалом.
   `--sheet client` закрывает client, пока зеркал employer ещё нет.
5. **Запись — только после явного «да»** на этот список. Согласие на прошлую неделю или другой
   табель не переносится.
   ```bash
   ~/.claude/skills/timesheet/timesheet apply --week W39 [--sheet client] --yes
   ```
   Запуск с `--yes` стоит под ask-правилом (`settings.global.example.json`). Повторный `apply`
   ничего не дублирует: сверяет журнал `sent.jsonl` и живые ворклоги (задача+день+секунды+комментарий).
6. **Проверка.** `timesheet summary --week W39` — в обоих табелях норма.
