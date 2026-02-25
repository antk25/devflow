# Dev Orchestrator

Система оркестрации разработки, построенная нативно на [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Координирует специализированных AI-агентов для планирования, реализации, тестирования и ревью задач — от постановки до готовой ветки с атомарными коммитами.

## Что умеет

- **Полностью автономный режим** — от описания задачи до финального коммита без подтверждений
- **Умная маршрутизация** — просто опиши задачу, оркестратор сам выберет workflow
- **Мульти-репозиторий** — проекты с раздельным frontend/backend
- **Двухветочная стратегия** — грязная work-ветка + чистая ветка с атомарными коммитами
- **Валидация архитектуры** — автоматическая проверка и исправление нарушений паттернов
- **E2E тестирование** — curl для API, Playwright для UI
- **Код-ревью** — локальные изменения, GitHub PR, GitLab MR
- **Пакетная очередь** — запланировать задачи на день и выполнить пакетом
- **Интеграция с Obsidian** — контрактная разработка (C-DAD) через vault

---

## Требования

### Обязательные

| Зависимость | Версия | Назначение |
|-------------|--------|------------|
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | 2.0+ | Основная платформа |
| [Node.js](https://nodejs.org/) | 20+ | MCP серверы, npm-скрипты |
| [Python](https://www.python.org/) | 3.10+ | Скрипты сессий и конфигурации |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | 0.4+ | Установка Serena через `uvx` |
| Git | 2.30+ | Управление версиями |
| [gum](https://github.com/charmbracelet/gum) | — | Интерактивное меню `start.sh` (не нужен при вызове `./start.sh <project>`) |

### MCP серверы (проектные)

Конфигурируются автоматически через `setup.sh`:

| Сервер | Назначение | Метод установки |
|--------|------------|-----------------|
| [Serena](https://github.com/oraios/serena) | Символьная навигация, персистентная память | `uvx` (автоматически) |
| qwen-review | Двойное код-ревью (Claude + Qwen) | Встроен, `npm install` |

### MCP серверы (опциональные, пользовательские)

Устанавливаются в `~/.claude.json` через `claude mcp add`. Без них оркестратор работает — зависящие фичи пропускаются.

| Сервер | Назначение | Команда установки |
|--------|------------|-------------------|
| [context7](https://github.com/upstash/context7) | Актуальная документация библиотек | `claude mcp add context7 -- npx -y @upstash/context7-mcp` |
| [playwright](https://github.com/anthropics/mcp-playwright) | E2E тестирование в браузере | `claude mcp add playwright -- npx -y @playwright/mcp@latest` |
| [chrome-devtools](https://github.com/nicholasgriffintn/chrome-devtools-mcp) | Отладка и профилирование браузера | `claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest` |
| [local-rag](https://github.com/jcassee/mcp-local-rag) | RAG база знаний для документации | `claude mcp add local-rag -- npx -y mcp-local-rag` |

---

## Быстрый старт

```bash
git clone <repo-url> claude-orchestrator
cd claude-orchestrator
./scripts/setup.sh    # генерирует .mcp.json, .claude/settings.json, пустые data-файлы
claude                # запускает Claude Code
```

При запуске увидите:

```
Dev Orchestrator

Просто опишите задачу — я выберу правильный workflow.
Или используйте команду напрямую:

/develop · /fix · /refactor · /explore · /investigate · /review
/plan · /implement · /finalize · /audit · /note · /queue
/next · /project · /help

Ready to build!
```

---

## Какую команду выбрать?

Можно не выбирать — просто опишите задачу. Оркестратор автоматически определит тип и запустит нужный workflow.

| Ситуация | Команда | Почему |
|----------|---------|--------|
| Новая фича | `/develop` | Полный пайплайн: план, реализация, тесты, ревью, атомарные коммиты |
| Идея без чёткого плана | `/explore` | Исследование подходов, без изменений |
| Баг (причина ясна) | `/fix` | Быстро, без планирования |
| Баг (причина неясна) | `/investigate` | Анализ и гипотезы, без изменений |
| Улучшение кода | `/refactor` | Пошагово, с сохранением поведения |
| Ревью своих изменений | `/review` | Перед коммитом |
| Ревью PR коллеги | `/review --pr 123` | Внешнее код-ревью |
| Грязная git-история | `/finalize` | Очистка work-ветки перед PR |
| Пакет задач на день | `/queue` | Добавить задачи, выполнить пакетом |
| Документация устарела | `/audit` | Сравнение docs с кодом |
| Заметки в Obsidian | `/note` | Сохранить/прочитать контракты и исследования |
| Ручной контроль | `/plan` + `/implement` | Пошагово с одобрением |

---

## Основные команды

### /develop — Автономная разработка

Полный пайплайн от описания задачи до готовой ветки:

```
/develop Добавить аутентификацию через JWT
/develop Реализовать экспорт данных в CSV
```

**Пайплайн:**
```
ветка → план → реализация → валидация архитектуры → E2E тесты → ревью → финализация
```

**Двухветочная стратегия:**
```
feature/auth-work  ← все итерации (15 грязных коммитов) — резервная копия
feature/auth       ← чистая ветка (3 атомарных коммита) — пушите эту
```

### /fix — Быстрое исправление

```
/fix Кнопка логина не реагирует
/fix TypeError в профиле пользователя
```

**Пайплайн:** `ветка → поиск → исправление → тест → коммит`

### /investigate — Анализ проблемы

Глубокий анализ **без изменений в коде**:

```
/investigate Логин не работает в Safari
/investigate Почему API отвечает медленно?
```

**Результат:** гипотезы с уверенностью, корневая причина, варианты решений с оценкой сложности.

### /refactor — Рефакторинг

```
/refactor src/services/auth.ts
/refactor --extract UserValidator from UserService
```

**Пайплайн:** `ветка → анализ → пошаговый рефакторинг → валидация → тесты → коммиты`

### /review — Код-ревью

```
/review                          # Staged-изменения
/review --pr 123                 # GitHub PR
/review --branch feature/auth    # Ветка vs main
/review --focus security         # Фокус на безопасности
```

### /explore — Исследование подхода

```
/explore Как лучше реализовать уведомления?
/explore Варианты кеширования для каталога
```

Исследует кодовую базу, сравнивает подходы, **не вносит изменений**.

### /finalize — Финализация коммитов

```
/finalize                        # Текущая ветка
/finalize feature/auth-work      # Конкретная ветка
```

Создаёт чистую ветку с атомарными коммитами из грязной work-ветки.

### /plan + /implement — Ручной режим

```
/plan Добавить корзину покупок     # PM создаёт план
/implement 1                      # Реализовать задачу #1
/implement 2                      # Реализовать задачу #2
/review                           # Ревью
/finalize                         # Очистка коммитов
```

### /queue — Пакетная очередь

```
/queue add develop Добавить тёмную тему
/queue add fix Исправить валидацию email
/queue list
/queue run                       # Выполнить все задачи
/queue status                    # Результаты
```

---

## Агенты

Система использует специализированных агентов для разных фаз:

| Агент | Роль | Когда используется |
|-------|------|-------------------|
| **PM** | Менеджер проекта | Анализ требований, декомпозиция задач |
| **Architect** | Системный архитектор | ADR, технические решения |
| **JS Developer** | JavaScript/TypeScript | React, Vue, Node.js, TypeScript |
| **PHP Developer** | PHP | Laravel, Symfony |
| **Tester** | QA-инженер | Unit, integration, E2E тесты |
| **Debugger** | Отладчик | Поиск корневых причин, диагностика |
| **Tracer** | Аналитик бизнес-логики | Трассировка потоков данных перед реализацией |
| **Reviewer** | Код-ревьюер (opus) | Безопасность, производительность, качество |
| **Architecture Guardian** | Валидатор паттернов | Проверка на соответствие паттернам проекта |

Агент выбирается автоматически по расширениям файлов, фреймворку и типу задачи.

---

## Git-стратегия

| Команда | Work-ветка | Финальная ветка | Коммиты |
|---------|------------|-----------------|---------|
| `/develop` | `feature/xxx-work` | `feature/xxx` | Атомарные (по стилю проекта) |
| `/fix` | — | `fix/xxx` | Один коммит |
| `/refactor` | — | `refactor/xxx` | По шагам |
| `/investigate` | — | — | Без изменений |
| `/review` | — | — | Без изменений |

**Безопасность:**
- `git push` **заблокирован** — вы всегда пушите вручную
- `gh` (GitHub CLI) **заблокирован** — PR создаёте сами
- Все изменения остаются локальными

Стиль коммитов анализируется из git-истории проекта и копируется (Conventional Commits, тикеты, plain text).

---

## Конфигурация проекта

Проекты регистрируются через `/project add <path>` и хранятся в `.claude/data/projects.json`:

```json
{
  "my-app": {
    "path": "/home/user/projects/my-app",
    "type": "fullstack",
    "serena_project": "my-app",
    "branch_prefix": "JIRA-",
    "repositories": {
      "backend": "/home/user/projects/my-app/backend",
      "frontend": "/home/user/projects/my-app/frontend"
    },
    "testing": {
      "backend": {
        "type": "api",
        "base_url": "http://localhost:8000",
        "commands": {
          "unit": "cd {{repo}} && ./vendor/bin/phpunit",
          "e2e": "curl -s {{base_url}}/api/health | jq ."
        }
      },
      "frontend": {
        "type": "browser",
        "base_url": "http://localhost:3000",
        "commands": {
          "unit": "cd {{repo}} && npm test",
          "e2e": "cd {{repo}} && npx playwright test"
        }
      }
    }
  }
}
```

Каждый проект может определить паттерны в `.claude/patterns.md` — оркестратор использует их при валидации кода.

---

## Структура проекта

```
claude-orchestrator/
├── .claude/
│   ├── CLAUDE.md                    # Контекст и правила маршрутизации
│   ├── settings.json.example        # Шаблон разрешений и хуков
│   ├── data/
│   │   ├── projects.json.example    # Шаблон реестра проектов
│   │   ├── sessions.json.example    # Шаблон отслеживания сессий
│   │   └── queue.json.example       # Шаблон очереди задач
│   ├── agents/                      # Системные промпты агентов
│   ├── hooks/                       # Хуки Claude Code
│   │   ├── auto-approve.sh          # Автоодобрение безопасных вызовов
│   │   ├── project-restore.sh       # Восстановление контекста при старте
│   │   └── rag-reindex-check.sh     # Проверка обновлений RAG базы
│   └── skills/                      # Определения slash-команд
├── scripts/
│   ├── setup.sh                     # Первоначальная настройка
│   ├── create-branch.sh             # Создание веток с конвенциями
│   ├── session-checkpoint.sh        # Отслеживание фаз сессий
│   └── ...                          # Утилиты для тестов, git, контрактов
├── mcp-servers/
│   └── qwen-review/                 # Встроенный MCP сервер
├── .mcp.json.example                # Шаблон конфигурации MCP
├── start.sh                         # Лаунчер проектов
└── README.md
```

---

## Устранение неполадок

**Всё ещё запрашивает подтверждения?**
1. Перезапустите Claude Code — изменения `settings.json` требуют перезапуска
2. Проверьте `chmod +x .claude/hooks/auto-approve.sh`
3. Крайний вариант: `claude --dangerously-skip-permissions`

**Git-операции не работают?**
- Git-команды должны запускаться из директории репозитория, а не из оркестратора

**E2E тесты падают?**
- Оркестратор фиксирует ошибку, пытается исправить (до 2 попыток), затем продолжает с ревью

---

## Лицензия

MIT
