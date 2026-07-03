import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { usePlanStore } from '../store/planStore';
import './TaskModal.css';

interface TaskModalProps {
  taskId: string;
  onClose: () => void;
  onSelectTask: (id: string) => void;
}

/** Renders in a portal to document.body rather than inline in the tree: a
 * fixed-position modal nested under an ancestor with a CSS transform/filter
 * (the Gantt chart's animated bars) would otherwise have its own `fixed`
 * positioning silently rebased to that ancestor instead of the viewport. */
export function TaskModal({ taskId, onClose, onSelectTask }: TaskModalProps) {
  const plan = usePlanStore((s) => s.plan);
  const schedule = usePlanStore((s) => s.schedule);
  const chatLog = usePlanStore((s) => s.chatLog);

  const task = useMemo(() => plan?.tasks.find((t) => t.id === taskId), [plan, taskId]);
  const sched = useMemo(() => schedule.find((s) => s.id === taskId), [schedule, taskId]);

  const predecessors = useMemo(() => {
    if (!task || !plan) return [];
    return task.predecessors
      .map((pid) => plan.tasks.find((t) => t.id === pid))
      .filter((t): t is NonNullable<typeof t> => Boolean(t));
  }, [task, plan]);

  // A per-task "agent edit history": tool-call chips in the chat log that
  // named this task's id directly, or that acted on this task's assignee
  // (shift_tasks/reassign_tasks don't enumerate ids up front, so assignee is
  // the best available signal for those). Nothing is fabricated — if the
  // chat log carries no matching entries, the section is simply empty.
  const editHistory = useMemo(() => {
    if (!task) return [];
    return chatLog.filter(
      (m): m is Extract<typeof m, { role: 'tool_call' }> =>
        m.role === 'tool_call' &&
        (m.taskIds.includes(taskId) ||
          (typeof m.args.assignee === 'string' && m.args.assignee === task.assignee) ||
          (typeof m.args.from_assignee === 'string' && m.args.from_assignee === task.assignee) ||
          (typeof m.args.to_assignee === 'string' && m.args.to_assignee === task.assignee)),
    );
  }, [chatLog, task, taskId]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  if (!task) return null;

  return createPortal(
    <div
      className="task-modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="task-modal"
        data-testid="task-modal"
        data-start={sched?.start ?? ''}
        data-end={sched?.end ?? ''}
        role="dialog"
        aria-modal="true"
        aria-label={task.name}
      >
        <div className="task-modal__header">
          <span className="task-modal__assignee">{task.assignee}</span>
          <button type="button" className="task-modal__close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>

        <h2 className="task-modal__title">{task.name}</h2>
        {task.description && <p className="task-modal__description">{task.description}</p>}

        <dl className="task-modal__stats">
          <div className="task-modal__stat">
            <dt>Начало</dt>
            <dd>{sched?.start ?? '—'}</dd>
          </div>
          <div className="task-modal__stat">
            <dt>Окончание</dt>
            <dd>{sched?.end ?? '—'}</dd>
          </div>
          <div className="task-modal__stat">
            <dt>Длительность</dt>
            <dd>{task.duration_days} д.</dd>
          </div>
          {sched?.is_critical && <div className="task-modal__stat task-modal__stat--critical">Критический путь</div>}
        </dl>

        <div className="task-modal__section">
          <h3>Предшественники</h3>
          {predecessors.length === 0 ? (
            <p className="task-modal__empty">Нет предшественников</p>
          ) : (
            <div className="task-modal__chips">
              {predecessors.map((pred) => (
                <button
                  key={pred.id}
                  type="button"
                  className="task-modal__chip"
                  data-testid="pred-chip"
                  onClick={() => onSelectTask(pred.id)}
                >
                  {pred.name}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="task-modal__section">
          <h3>История правок агентом</h3>
          {editHistory.length === 0 ? (
            <p className="task-modal__empty">Агент ещё не менял эту задачу</p>
          ) : (
            <ul className="task-modal__history" data-testid="task-history">
              {editHistory.map((entry, i) => (
                <li key={i} className="task-modal__history-item">
                  <span className="task-modal__history-glyph" aria-hidden="true">
                    »
                  </span>
                  {entry.tool}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
