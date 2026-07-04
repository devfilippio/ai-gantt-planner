import { usePlanStore } from '../store/planStore';
import './CommandsGuide.css';

interface GuideCommand {
  text: string;
  category: string;
}

// Exactly the 8 commands from the one-pager PDF (§02 block) — the owner
// explicitly asked for this list verbatim, in this order.
const COMMANDS: GuideCommand[] = [
  { text: 'перенеси задачи Олега на неделю', category: 'массовый сдвиг' },
  { text: 'переназначь задачи Марии на Анну', category: 'переназначение' },
  {
    text: 'добавь задачу Настройка аналитики, Иван, 3 дня, после вёрстки',
    category: 'добавление',
  },
  { text: 'увеличь длительность QA до 8 дней', category: 'правка' },
  { text: 'свяжи запуск с QA и дизайном', category: 'зависимости' },
  { text: 'купить молоко с 11 по 18 июля', category: 'точные даты' },
  { text: 'кто самый загруженный?', category: 'аналитика' },
  { text: 'отмени последнее изменение', category: 'откат' },
];

export function CommandsGuide() {
  const setDraftCommand = usePlanStore((s) => s.setDraftCommand);

  return (
    <section className="commands-guide" data-testid="commands-guide">
      <span className="commands-guide__title">
        § 02 · КОМАНДЫ — ПРОСТО ГОВОРИТЕ, ЧТО НУЖНО
      </span>

      <div className="commands-guide__grid">
        {COMMANDS.map((cmd) => (
          <button
            key={cmd.text}
            type="button"
            className="commands-guide__card"
            data-testid="guide-cmd"
            onClick={() => setDraftCommand(cmd.text)}
          >
            <span className="commands-guide__glyph" aria-hidden="true">
              »
            </span>
            <span className="commands-guide__text">{cmd.text}</span>
            <span className="commands-guide__category">{cmd.category}</span>
          </button>
        ))}
      </div>

      <p className="commands-guide__footnote">
        Импорт и экспорт Excel — в тулбаре сверху · клик по задаче — карточка с деталями · «Откатить»
        отменяет ход агента
      </p>
    </section>
  );
}
