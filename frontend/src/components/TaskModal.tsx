import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { usePlanStore } from '../store/planStore';
import { daysBetween, formatRuDateLong, todayISO } from '../gantt/geometry';
import { summarizeToolCall } from '../lib/toolSummary';
import type { Scheduled } from '../types';
import './TaskModal.css';

interface TaskModalProps {
  taskId: string;
  onClose: () => void;
  onSelectTask: (id: string) => void;
}

const MINI_TIMELINE_HEIGHT = 40;
const MIN_DURATION_DAYS = 1;

/** Renders in a portal to document.body rather than inline in the tree: a
 * fixed-position modal nested under an ancestor with a CSS transform/filter
 * (the Gantt chart's animated bars) would otherwise have its own `fixed`
 * positioning silently rebased to that ancestor instead of the viewport. */
export function TaskModal({ taskId, onClose, onSelectTask }: TaskModalProps) {
  const plan = usePlanStore((s) => s.plan);
  const schedule = usePlanStore((s) => s.schedule);
  const chatLog = usePlanStore((s) => s.chatLog);
  const changedIds = usePlanStore((s) => s.changedIds);
  const resizeTask = usePlanStore((s) => s.resizeTask);

  const task = useMemo(() => plan?.tasks.find((t) => t.id === taskId), [plan, taskId]);
  const sched = useMemo(() => schedule.find((s) => s.id === taskId), [schedule, taskId]);

  const predecessors = useMemo(() => {
    if (!task || !plan) return [];
    return task.predecessors
      .map((pid) => plan.tasks.find((t) => t.id === pid))
      .filter((t): t is NonNullable<typeof t> => Boolean(t));
  }, [task, plan]);

  // Tasks that name this one as a predecessor — the inverse of `predecessors`
  // above. Lets the modal answer "what depends on this?" as well as "what
  // does this depend on?", both one click away via the same chip pattern.
  const successors = useMemo(() => {
    if (!plan) return [];
    return plan.tasks.filter((t) => t.predecessors.includes(taskId));
  }, [plan, taskId]);

  // Slack ("запас"): how many calendar days this task's end could slip
  // before it would delay a successor (or, for a terminal task, before it
  // would push past the overall project end). Zero-or-negative slack tasks
  // are exactly the critical path, which already has its own badge — this
  // stat is the complementary "how much room do I have" read for everyone
  // else. Computed client-side from the schedule already in the store, no
  // extra request.
  const slackDays = useMemo(() => {
    if (!sched || !plan) return null;
    const successorStarts = successors
      .map((s) => schedule.find((row) => row.id === s.id))
      .filter((row): row is Scheduled => Boolean(row))
      .map((row) => daysBetween(sched.end, row.start));
    if (successorStarts.length > 0) {
      return Math.min(...successorStarts);
    }
    // No successors — measure slack against the overall project end (the
    // latest scheduled end across all tasks).
    const projectEnd = schedule.reduce(
      (latest, row) => (row.end > latest ? row.end : latest),
      sched.end,
    );
    return daysBetween(sched.end, projectEnd);
  }, [sched, plan, successors, schedule]);

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

  // Mini timeline geometry: every task as a proportional ghost bar across
  // the project's full date span, purely presentational (no scales, no
  // interaction) — just enough to place this task in the overall plan at a
  // glance. Uses the same UTC day-diff math as the main chart's geometry
  // helpers, projected onto a 0..1 fraction of the project span so it scales
  // to whatever width the modal renders at.
  const miniTimeline = useMemo(() => {
    if (!plan || schedule.length === 0) return null;
    const projectStart = plan.project_start;
    const projectEnd = schedule.reduce(
      (latest, row) => (row.end > latest ? row.end : latest),
      schedule[0].end,
    );
    const totalSpan = Math.max(daysBetween(projectStart, projectEnd), 1);

    const bars = plan.tasks
      .map((t) => {
        const row = schedule.find((s) => s.id === t.id);
        if (!row) return null;
        const x0 = daysBetween(projectStart, row.start) / totalSpan;
        const x1 = daysBetween(projectStart, row.end) / totalSpan;
        return { id: t.id, x0, x1: Math.max(x1, x0 + 0.002) };
      })
      .filter((b): b is { id: string; x0: number; x1: number } => Boolean(b));

    const todayOffsetDays = daysBetween(projectStart, todayISO());
    const todayFrac = todayOffsetDays / totalSpan;
    const isTodayVisible = todayFrac >= 0 && todayFrac <= 1;
    return { bars, todayFrac, isTodayVisible };
  }, [plan, schedule]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  if (!task) return null;

  const isJustChanged = changedIds.includes(task.id);
  const initial = task.assignee.trim().charAt(0).toUpperCase() || '?';

  const handleDurationChange = (delta: number) => {
    const next = Math.max(MIN_DURATION_DAYS, task.duration_days + delta);
    if (next === task.duration_days) return;
    void resizeTask(task.id, { duration_days: next });
  };

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
          <span className="task-modal__assignee-tag">{task.assignee}</span>
          <button type="button" className="task-modal__close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>

        {miniTimeline && (
          <svg
            className="task-modal__mini-timeline"
            data-testid="task-mini-timeline"
            viewBox={`0 0 100 ${MINI_TIMELINE_HEIGHT}`}
            preserveAspectRatio="none"
          >
            {miniTimeline.bars.map((b) => {
              const isSelf = b.id === task.id;
              return (
                <rect
                  key={b.id}
                  className="task-modal__mini-bar"
                  data-self={isSelf}
                  data-changed={isSelf && isJustChanged}
                  x={`${b.x0 * 100}%`}
                  width={`${Math.max((b.x1 - b.x0) * 100, 0.6)}%`}
                  y={isSelf ? MINI_TIMELINE_HEIGHT / 2 - 3 : MINI_TIMELINE_HEIGHT / 2 - 1.25}
                  height={isSelf ? 6 : 2.5}
                  rx={isSelf ? 2 : 1}
                />
              );
            })}
            {miniTimeline.isTodayVisible && (
              <line
                className="task-modal__mini-today"
                x1={`${miniTimeline.todayFrac * 100}%`}
                x2={`${miniTimeline.todayFrac * 100}%`}
                y1={0}
                y2={MINI_TIMELINE_HEIGHT}
              />
            )}
          </svg>
        )}

        <h2 className="task-modal__title">{task.name}</h2>
        {task.description && <p className="task-modal__description">{task.description}</p>}

        <p className="task-modal__dates">
          {sched ? formatRuDateLong(sched.start, sched.end) : '—'}
        </p>

        <dl className="task-modal__stats">
          <div className="task-modal__stat">
            <dt>Исполнитель</dt>
            <dd className="task-modal__assignee-chip">
              <span className="task-modal__assignee-dot" aria-hidden="true">
                {initial}
              </span>
              {task.assignee}
            </dd>
          </div>
          <div className="task-modal__stat">
            <dt>Длительность</dt>
            <dd>
              <div className="task-modal__stepper">
                <button
                  type="button"
                  className="task-modal__stepper-btn"
                  data-testid="duration-dec"
                  disabled={task.duration_days <= MIN_DURATION_DAYS}
                  onClick={() => handleDurationChange(-1)}
                  aria-label="Уменьшить длительность"
                >
                  −
                </button>
                <span className="task-modal__stepper-value">{task.duration_days} д</span>
                <button
                  type="button"
                  className="task-modal__stepper-btn"
                  data-testid="duration-inc"
                  onClick={() => handleDurationChange(1)}
                  aria-label="Увеличить длительность"
                >
                  +
                </button>
              </div>
            </dd>
          </div>
          <div className="task-modal__stat task-modal__stat--wide">
            {sched?.is_critical ? (
              <span className="task-modal__badge task-modal__badge--critical">Критический путь</span>
            ) : (
              slackDays !== null && <span className="task-modal__badge">Запас: {slackDays} дн.</span>
            )}
          </div>
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
          <h3>Зависят от этой задачи</h3>
          {successors.length === 0 ? (
            <p className="task-modal__empty">Ни одна задача не зависит от этой</p>
          ) : (
            <div className="task-modal__chips">
              {successors.map((succ) => (
                <button
                  key={succ.id}
                  type="button"
                  className="task-modal__chip"
                  data-testid="succ-chip"
                  onClick={() => onSelectTask(succ.id)}
                >
                  {succ.name}
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
                  {summarizeToolCall(entry.tool, entry.args)}
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
