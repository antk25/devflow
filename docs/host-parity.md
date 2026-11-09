# Claude Code, Codex и запасной pi

Каждая модель работает в родной среде: research, plan и ревью — Opus в Claude Code, gpt-sol / gpt-astra в Codex; implement — те же модели с effort low там же. pi — только запасной путь для implement, когда лимиты исчерпаны: дешёвая модель OpenRouter из раздела `pi` в `model-policy.json` (сейчас `openrouter/z-ai/glm-5.3-flash`). Фазы без записи в этом разделе pi отклоняет, модели `openai-codex` в pi запрещены. Полный цикл research → plan → implement в pi и смена среды посреди шага в обе стороны больше не цель.

## Автоматические доказательства

- `python3 -m pytest -q tests/test_host_parity.py tests/test_install_agents.py tests/test_pi.py`: 78 passed (после правки устаревшего теста запуска pi — 81 с `tests/test_browser_secret_evidence.py`). Временные git/vault/SQLite, зависимости, partial/blocked, interrupt/resume, reopen, новый гейт редакции с сохранением завершённого определения и истории; подставные процессы фаз, replan, установка и удаление.
- В этот набор входит загрузка TypeScript-расширения настоящим установленным загрузчиком pi (`test_real_pi_loader_does_not_duplicate_extension`), без запроса модели: одно расширение, ноль ошибок API. Это не проверка всей интерактивной сессии.
- `node --test tests/pi/*.test.mjs`: 13 passed, включая guard, общие инструкции и WARN/CUT.
- Повторная проверка только отслеживаемых файлов (`git archive HEAD`) во временной копии с отдельным HOME: **799 passed**. Для импорта pytest использован `PYTHONPATH=/home/smg25/.local/lib/python3.12/site-packages`. Пользовательский каталог combos повторно не проверялся и не менялся. Отслеживаемый тест ожидает фиксированные пять имён, а `bench.combos()` читает все `*.json`: дополнительный пользовательский набор — отдельное исходное ограничение полного запуска в рабочем дереве, не исправление этого шага.
- Повтор browser выполнялся после подготовки учебного git/vault/AGENTS.md вызывающим. Роль остановила Chrome (exit 0), но получила «Не хватает» при вводе `@env:PARITY_FAKE_SECRET`: переменная не настроена. **1/5**, save/replay и управляемый провал не выполнены. Файл секретов не читался и не менялся; сервер пользователя не запускался и не останавливался.

## Осталось

- Живой прогон `devflow phase run <slug> implement` в pi на `openrouter/z-ai/glm-5.3-flash`: шаг доведён до `devflow finish`. Сделать при первом исчерпании лимитов или на учебном проекте; если Flash не справится — `z-ai/glm-5.3`, затем `moonshotai/kimi-k3.1-pro`.

Ниже — история приёмки до запрета Codex в pi (коммит 2403f53): команды с `openai-codex/*` в pi теперь отклоняются.

## Точная проверка очистки — run 43811632-404f-4315-a2b4-ed47b6237875

Исследована именно установленная версия `chrome-devtools-mcp@1.10.1` (npm cache `ba38acecdf97096f`), не соседняя 1.11.0. `daemon/utils.js` задаёт путь session → daemon.pid; daemon запускает MCP с унаследованным окружением, BrowserManager передаёт isolated-профиль Puppeteer. Новый диагностический помощник `scripts/browser_session_evidence.py` только читает процессы и сохраняет доказательства:

```text
python3 scripts/browser_session_evidence.py capture <session> <json>
devflow-browser <session> stop
python3 scripts/browser_session_evidence.py verify <session> <json>
```

Capture выполняется после навигации, до stop: проверяет session в окружении PID из metadata, команду демона, единственный профиль, потомков и starttime. Verify учитывает переподчинённых потомков, новые процессы с session/profile и повторное использование PID. Завершённые zombie не считаются работающим Chrome. Не используются общий pgrep или kill чужих процессов. Недоступное окружение потенциального Chrome/Node приводит к отказу проверки, а не к успеху.

Новый browser-процесс `openai-codex/gpt-6.1-sol:low`: success, replay и ожидаемый отрицательный API500 прошли; у каждой сессии verify exit0, `live_owned_processes=[]`. Доказательства: `/tmp/devflow-smoke/df-pi-workflow-parity-school-cleanup/{success,replay,failure}.json`. Отрицательный тест правильно отмечен ✅.

Формальный вердикт **6/7 с «Не хватает»**: роль пыталась искать фиктивное значение в переменной процесса, хотя `DEVFLOW_BROWSER_ENV` указывает на файл для обёртки и не экспортирует его содержимое. Это не дефект cleanup или API. Implement отдельно проверил отсутствие значения в двух файлах (вердикт и сохранённый скрипт): PASS, значение не печаталось. Однако этот результат не переписывает вердикт роли: обязательный протокол требует blocked при «Не хватает». Повтор browser не выполнялся. Для следующего задания нужно заранее предоставить безопасный проверяющий скрипт, читающий только подготовленный фиктивный файл, а не требовать экспортированной переменной. Никаких действий с Chrome пользователю уже не требуется.

После закрытия browser (см. run 298e2b59 ниже) остаются только пункты 1–3 и 5 выше: два живых цикла с пользовательскими гейтами, recovery в обе стороны и независимые реальные источники ревью. Они означают partial, не повод запускать Claude из pi. Исторические 799/78/13 здесь не запускались повторно.

## Формальная проверка секрета — run 5f746865-ffde-4a49-89f1-c8441879f837

Добавлен `scripts/browser_secret_evidence.py`: читает только указанный файл окружения, ищет значение переменной в перечисленных артефактах и печатает лишь `PASS`/`FAIL` без значения; аргументы позиционные, потому что guard pi отклоняет вызовы неизвестных скриптов с опциями (`shell-uncertain`). Стенд запущен и остановлен implement; учебный проект пересобран (прежний `/tmp` очищен).

```text
python3 scripts/browser_secret_evidence.py <browser.env> PARITY_FAKE_SECRET <verdict.md> <smoke-<slug>.sh>
```

Два прогона browser `openai-codex/gpt-6.1-sol:low`: 5/7 (guard отклонил опции `--env-file`) и после исправления 4/6. Сценарий, replay (exit 0), ожидаемый API500 и cleanup failure-сессии (verify exit0, `live_owned_processes=[]`) подтверждены. Роль не выполнила проверку секрета: задание требовало записать `verdict.md` до проверки, а правило роли — один `Write` вердикта последним действием; вторая ❌ — одна сессия на прогон вместо отдельных success/failure. Implement выполнил ту же команду поверх шести артефактов обоих прогонов: `PASS`, значение не печаталось. По протоколу — blocked без третьего прогона. Для следующего задания: проверять скрипт и черновик `/tmp/devflow-smoke/<slug>/draft.md`, а не `verdict.md`; требовать одно capture/verify на единственную сессию.

## Браузерная приёмка закрыта — run 298e2b59-6e02-4c84-b4de-19eeebca0d7d

Роль browser отказала заданию с двумя сессиями и черновиком `draft.md` («Не хватает»: один `start` на прогон, запись только скриншотов и `verdict.md`). Поэтому успех и провал разведены по двум прогонам runner с разными slug; проверка секрета выполняется ролью над сохранённым скриптом и capture-JSON до записи вердикта, а сам `verdict.md` проверяет вызывающий после.

```text
devflow agent run browser --message-file <A|B> --model openai-codex/gpt-6.1-sol:low --timeout 420
python3 scripts/browser_secret_evidence.py <browser.env> PARITY_FAKE_SECRET <smoke-<slug>.sh> <success.json>
```

Прогон A (`…-school-success`): **4/4** — «Готово»/`[200]`, verify после stop exit 0 и `live_owned_processes=[]` в `success.json`, replay сохранённого скрипта exit 0, `PASS` проверки секрета. Прогон B (`…-school-failure`): **3/3** — «Ошибка»/`[500]`, verify exit 0 в `failure.json`, `PASS`. Implement повторил проверку секрета поверх обоих вердиктов, JSON и скрипта (7 артефактов): `PASS`; verify обеих сессий повторно exit 0. Стенд запущен и остановлен implement. Устаревший `test_implement_launch_failure_interrupts_the_run` переведён на `Popen`; целевой набор 81 passed, Node 13 passed.

## Не входит в заявленную совместимость

Учёт токенов и статистика pi; timesheet/recap и board; standup/изолированное чтение Jira, jira-create, page, transcribe, retro, maintain, autoresearch и остальные вспомогательные skills. Их существующая установка не означает подтверждённую работу в pi. Guard не является изоляцией ОС/сети и не повторяет скрытый классификатор Claude.
