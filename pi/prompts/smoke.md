---
description: Проверить сценарий отдельной ролью browser
argument-hint: "[env: local;] slug: <slug>; [save;] <сценарий>"
---
Прочитай skills/smoke/SKILL.md из установленного DevFlow и выполни раздел «Запуск в pi».
Аргументы: $ARGUMENTS
Не выполняй сценарий в контексте драйвера: используй devflow agent run browser,
проверь exit_code, прочитай файл вердикта и верни его дословно.
