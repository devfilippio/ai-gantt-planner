# AI Gantt Planner — тестовое задание (Full-stack AI-native, React + FastAPI)

## Что это

Тестовое задание на позицию Full-stack разработчика AI-native продукта. **От качества зависит карьера владельца — планка: «однозначно вау».** ТЗ: `C:\Users\flowz\Downloads\Telegram Desktop\test_task.pdf`.

Продукт: веб-страница с интерактивной диаграммой Гантта (сид-данные при первом открытии), рядом чат — LLM-агент массово редактирует план на естественном языке (перенос задач, зависимости, добавление, переназначение исполнителей). Изменения мгновенно отражаются на диаграмме. Клик по задаче — модалка с деталями. Импорт/экспорт Excel (колонки: задача, описание, исполнитель, длительность, предшественники).

## Сдаём (deliverables)

1. Git-репозиторий (осмысленная история коммитов — её тоже читают).
2. Задеплоенное приложение — **Vercel**.
3. README: запуск, архитектура, решения, **отдельный раздел «как использовали AI-ассистентов»**.
4. Демо-видео/gif: загрузка Excel → правка через чат → экспорт (делаем через remotion-superpowers).
5. Пример Excel (`sample-data/plan.xlsx`).
6. `docs/roadmap-to-production.md` — техдолги, риски, порядок закрытия.

## Утверждённая архитектура

Монорепо, один проект Vercel, один URL:

```
frontend/          # Vite + React 19 + TS + Zustand
api/               # FastAPI (Vercel Python runtime, Fluid Compute)
  index.py         # входная точка
  scheduler.py     # топологический расчёт дат, критический путь, детекция циклов
  excel.py         # import/export (openpyxl)
  agent.py         # LLM-агент: OpenRouter, цикл tool-calling, SSE-стрим
  tools.py         # ЕДИНЫЙ набор инструментов — использует и агент, и MCP
  mcp_server.py    # MCP streamable HTTP на /api/mcp (официальный Python SDK)
sample-data/
docs/
vercel.json
```

Ключевые решения (утверждены):
- **Гантт — полностью кастомный (SVG + React)**, вариант «A». Никаких Gantt-библиотек.
- **БД — Neon Postgres** (Vercel Marketplace): задачи + снапшоты плана (undo ходов агента).
- **Даты не хранятся** — вычисляются: `start = max(end предшественников)`, `end = start + duration`. Критический путь подсвечивается.
- **LLM:** `anthropic/claude-sonnet-4.5` через OpenRouter, фолбэк `openai/gpt-4o`. Ключ даёт владелец → env `OPENROUTER_API_KEY` (Vercel env + `.env`, в git не коммитить).
- **Мгновенность:** `POST /api/chat` стримит SSE-события `{tool, args, plan_patch}` — фронт применяет патчи live.
- **MCP-инструменты:** `get_plan`, `add_task`, `update_task`, `delete_task`, `set_dependencies`, `reassign_tasks`, `shift_tasks`, `undo_last_turn`. Тот же `/api/mcp` подключается к Claude Desktop/Cursor — описать в README.
- **WebSocket на Vercel нет и не нужен** — SSE закрывает требование.

## Дизайн-направление (зафиксировано)

Эстетика filipp.io (`D:\AI\misite\filipp.io\CLAUDE.md` — прочитать перед фронтом): Vercel × Linear, тёмный editorial-minimal. `#0a0a0a` фон, hairline-сетка `#1c1c1f`, текст `#fafafa`/`#a1a1aa`, моноширинные лейблы `§ 01 · ПЛАН ПРОЕКТА`, **единственный акцент — зелёный `#34d399`** (изменения агента) + янтарный пунктир «сегодня». Бары: серые `#27272a`, критический путь — белые `#e4e4e7`. Никаких градиентов, glassmorphism, emoji, радуги.

Референс-мокап согласован с владельцем (виджет в сессии от 2026-07-03): слева Гантт с колонкой задач и стрелками-безье зависимостей, справа чат-панель с tool-call чипами и кнопкой «Откатить», тулбар с «Импорт Excel»/«Экспорт».

**Главный вау-момент:** правка агента → бары анимированно переезжают (spring ~400ms) с затухающей подсветкой изменённого + чип в чате. Это кадр для демо-gif.

Сид: план «Запуск мобильного приложения», ~25 задач, 5 исполнителей, ветвящиеся зависимости.

## Скиллы — когда что использовать

| Скилл | Когда |
|---|---|
| `superpowers:writing-plans` | Следующий шаг после спеки — план имплементации |
| `superpowers:test-driven-development` | Вся имплементация: scheduler, excel, tools — сначала тесты (pytest) |
| `superpowers:subagent-driven-development` | Исполнение плана субагентами |
| `frontend-design:frontend-design` | Каждый UI-компонент |
| `impeccable` (ставится) | `/polish`, `/audit` UI перед деплоем — анти-AI-slop |
| `design-motion` (ставится) | Аудит анимаций Гантта (spring-переезды баров) |
| `taste-skill` (ставится) | Вариативность/характер дизайна |
| `remotion-superpowers` (ставится) | Демо-видео из ТЗ — кодом |
| `guardrails` (ставится) | Системный промпт агента + раздел рисков в Roadmap |
| `playwright-skill` / playwright-mcp | E2E smoke основного сценария, скриншот-проверка UI |
| `scope-hammer` | Если скоуп поплыл — резать скоуп, не срок |
| `superpowers:verification-before-completion` | Перед любым «готово» |
| `code-review` | Перед финальной сдачей |

## Процесс и статус

Процесс: brainstorming ✅ → дизайн утверждён ✅ (вариант A, Vercel, Neon, SSE, MCP) → **спека** ✅ (`docs/superpowers/specs/`) → writing-plans ✅ → TDD-имплементация ✅ → code-review ✅ → README/Roadmap ✅ → демо ✅ → деплой ✅.

Статус на 2026-07-03: **задеплоено и проверено на проде.** Live: https://ai-gantt-planner-psi.vercel.app. Backend (32 pytest) + frontend (`npm run build`) + E2E (12 Playwright-спеков на desktop, включая `golden-path` и `demo`) — все зелёные. На проде проверены сквозным прогоном: SPA, `/api/health`, `/api/plan`, экспорт Excel, чат с живой моделью OpenRouter (SSE), MCP-handshake (`/api/mcp/`). Ключ OpenRouter — в Vercel env (Production/Preview/Development). Деплой на MemoryStore (без Neon) — план сбрасывается на cold start; провижининг Neon + `psycopg` под Python 3.13 вынесены в Roadmap. Осталось опционально: git-remote на GitHub для deliverable «ссылка на репозиторий».

## Правила

- Общение и документы — на русском; код и коммиты — на английском; README и docs — на русском (решение владельца от 2026-07-03).
- Секреты только в env; `.env` в `.gitignore` с первого коммита.
- Каждый этап проверяется локально (`uvicorn` + `vite dev`), потом Vercel preview, потом прод.
- Windows: PowerShell-среда, поэтому в скриптах учитывать кодировку (PYTHONIOENCODING=utf-8 при выводе кириллицы из Python).
