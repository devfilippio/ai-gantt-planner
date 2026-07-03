import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { usePlanStore } from '../store/planStore';
import { daysBetween, dependencyPath, monthSpans, taskBar, weekTicks } from '../gantt/geometry';
import type { Bar } from '../gantt/geometry';
import type { Scheduled, Task } from '../types';
import './GanttChart.css';

const ROW_HEIGHT = 40;
const BAR_HEIGHT_RATIO = 0.6; // bar height as a fraction of the row band
const MIN_BAR_WIDTH = 18; // short tasks still read as a bar + keep the resize handle usable
const HEADER_H = 40; // two-tier timeline header: month strip + week/date strip
const HEADER_SPLIT = HEADER_H / 2; // y where the month strip ends and the week strip begins
const DAY_WIDTH_DAY_ZOOM = 34;
const DAY_WIDTH_WEEK_ZOOM = 12;
const CHART_PADDING_DAYS = 6; // trailing whitespace so the last bar isn't flush against the edge

/**
 * Fixed "today" reference for the demo: project_start + 12 calendar days.
 * The seed plan's `project_start` (2026-05-05) is itself a fixed constant,
 * so anchoring "today" to it (rather than the real wall-clock date) keeps
 * the chart's most interesting moment — mid-build, roughly halfway through
 * the 7-task "Запуск лендинга" plan — reproducible across every screenshot,
 * demo, and Playwright run.
 */
const TODAY_OFFSET_DAYS = 12;

type Zoom = 'day' | 'week';

interface GanttChartProps {
  onSelectTask?: (id: string) => void;
}

interface DragState {
  taskId: string;
  originDurationDays: number;
  originEnd: string;
  pointerStartX: number;
  dayWidth: number;
  previewDurationDays: number;
}

export function GanttChart({ onSelectTask }: GanttChartProps) {
  const plan = usePlanStore((s) => s.plan);
  const schedule = usePlanStore((s) => s.schedule);
  const changedIds = usePlanStore((s) => s.changedIds);
  const resizeTask = usePlanStore((s) => s.resizeTask);

  const [zoom, setZoom] = useState<Zoom>('day');
  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const hasCenteredToday = useRef(false);

  const dayWidth = zoom === 'day' ? DAY_WIDTH_DAY_ZOOM : DAY_WIDTH_WEEK_ZOOM;
  const projectStart = plan?.project_start ?? '2026-05-05';

  const scheduleById = useMemo(() => {
    const map = new Map<string, Scheduled>();
    for (const s of schedule) map.set(s.id, s);
    return map;
  }, [schedule]);

  const tasks: Task[] = useMemo(() => plan?.tasks ?? [], [plan]);

  const totalDays = useMemo(() => {
    let max = 30;
    for (const s of schedule) {
      max = Math.max(max, daysBetween(projectStart, s.end));
    }
    return max + CHART_PADDING_DAYS;
  }, [schedule, projectStart]);

  const chartWidth = totalDays * dayWidth;
  const rowsHeight = tasks.length * ROW_HEIGHT;
  const chartHeight = rowsHeight + HEADER_H;

  const bars = useMemo(() => {
    const map = new Map<string, Bar>();
    tasks.forEach((task, rowIndex) => {
      const sched = scheduleById.get(task.id);
      if (!sched) return;
      map.set(task.id, taskBar(sched, rowIndex, ROW_HEIGHT, dayWidth, projectStart, HEADER_H));
    });
    return map;
  }, [tasks, scheduleById, dayWidth, projectStart]);

  const ticks = useMemo(
    () => weekTicks(projectStart, totalDays, dayWidth),
    [projectStart, totalDays, dayWidth],
  );

  const months = useMemo(
    () => monthSpans(projectStart, totalDays, dayWidth),
    [projectStart, totalDays, dayWidth],
  );

  const todayX = TODAY_OFFSET_DAYS * dayWidth;

  // Bring "today" into view on first load — the most relevant moment in the
  // plan shouldn't require a manual scroll to discover. Runs once per mount
  // (not on every zoom change) so a deliberate user scroll is never yanked
  // back mid-session.
  useEffect(() => {
    if (hasCenteredToday.current) return;
    const el = scrollRef.current;
    if (!el || tasks.length === 0) return;
    hasCenteredToday.current = true;
    const target = Math.max(0, todayX - el.clientWidth / 2);
    el.scrollLeft = target;
  }, [tasks.length, todayX]);

  const dependencies = useMemo(() => {
    const paths: { key: string; d: string }[] = [];
    for (const task of tasks) {
      const toBar = bars.get(task.id);
      if (!toBar) continue;
      for (const predId of task.predecessors) {
        const fromBar = bars.get(predId);
        if (!fromBar) continue;
        paths.push({ key: `${predId}->${task.id}`, d: dependencyPath(fromBar, toBar) });
      }
    }
    return paths;
  }, [tasks, bars]);

  const handleResizeStart = useCallback(
    (task: Task, sched: Scheduled) => (event: ReactPointerEvent<SVGRectElement>) => {
      event.stopPropagation();
      event.preventDefault();
      (event.target as Element).setPointerCapture(event.pointerId);
      const state: DragState = {
        taskId: task.id,
        originDurationDays: task.duration_days,
        originEnd: sched.end,
        pointerStartX: event.clientX,
        dayWidth,
        previewDurationDays: task.duration_days,
      };
      dragRef.current = state;
      setDrag(state);
    },
    [dayWidth],
  );

  const handlePointerMove = useCallback((event: ReactPointerEvent<SVGSVGElement>) => {
    const state = dragRef.current;
    if (!state) return;
    const deltaPx = event.clientX - state.pointerStartX;
    const deltaDays = Math.round(deltaPx / state.dayWidth);
    const nextDuration = Math.max(1, state.originDurationDays + deltaDays);
    if (nextDuration !== state.previewDurationDays) {
      const next = { ...state, previewDurationDays: nextDuration };
      dragRef.current = next;
      setDrag(next);
    }
  }, []);

  const handlePointerUp = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const state = dragRef.current;
      if (!state) return;
      dragRef.current = null;
      setDrag(null);
      if (state.previewDurationDays !== state.originDurationDays) {
        void resizeTask(state.taskId, { duration_days: state.previewDurationDays });
      }
      if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    },
    [resizeTask],
  );

  return (
    <section className="gantt" data-testid="gantt-chart">
      <div className="gantt__header">
        <span className="gantt__title">§ 01 · ПЛАН ПРОЕКТА</span>
        <div className="gantt__zoom" role="group" aria-label="Масштаб">
          <button
            type="button"
            className="gantt__zoom-btn"
            data-active={zoom === 'day'}
            onClick={() => setZoom('day')}
          >
            ДЕНЬ
          </button>
          <button
            type="button"
            className="gantt__zoom-btn"
            data-active={zoom === 'week'}
            onClick={() => setZoom('week')}
          >
            НЕДЕЛЯ
          </button>
        </div>
      </div>

      <div className="gantt__rows" style={{ ['--row-height' as string]: `${ROW_HEIGHT}px` }}>
        <div className="gantt__rows-spacer" style={{ height: HEADER_H }} aria-hidden="true" />
        {tasks.map((task, rowIndex) => (
          <div key={task.id} className="gantt__row" data-alt={rowIndex % 2 === 1}>
            <span className="gantt__row-name">{task.name}</span>
            <span className="gantt__row-assignee">{task.assignee}</span>
          </div>
        ))}
      </div>

      <div className="gantt__scroll" ref={scrollRef}>
        <svg
          className="gantt__svg"
          width={chartWidth}
          height={Math.max(chartHeight, ROW_HEIGHT + HEADER_H)}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          <defs>
            <marker
              id="dep-arrowhead"
              viewBox="0 0 8 8"
              refX="6.5"
              refY="4"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0.5 L 7 4 L 0 7.5 z" fill="var(--text-mute)" />
            </marker>
            <filter id="bar-shadow" x="-20%" y="-60%" width="140%" height="260%">
              <feDropShadow dx="0" dy="1.5" stdDeviation="1.5" floodColor="#000000" floodOpacity="0.45" />
            </filter>
          </defs>

          {/* Alternating row bands — barely-there, helps the eye track a row across the width */}
          {tasks.map((task, rowIndex) =>
            rowIndex % 2 === 1 ? (
              <rect
                key={`band-${task.id}`}
                className="gantt__row-band"
                x={0}
                y={rowIndex * ROW_HEIGHT + HEADER_H}
                width={chartWidth}
                height={ROW_HEIGHT}
              />
            ) : null,
          )}

          {/* Week grid (below header) */}
          {ticks.map((tick) => (
            <line
              key={tick.x}
              className="gantt__grid-line"
              x1={tick.x}
              x2={tick.x}
              y1={HEADER_H}
              y2={Math.max(chartHeight, ROW_HEIGHT + HEADER_H)}
            />
          ))}

          {/* Today line */}
          {todayX <= chartWidth && (
            <g data-testid="today-line">
              <line
                className="gantt__today-line"
                x1={todayX}
                x2={todayX}
                y1={HEADER_H}
                y2={Math.max(chartHeight, ROW_HEIGHT + HEADER_H)}
              />
              <text
                className="gantt__today-label"
                x={todayX + 5}
                y={Math.max(chartHeight, ROW_HEIGHT + HEADER_H) - 6}
              >
                СЕГОДНЯ
              </text>
            </g>
          )}

          {/* Dependency arrows (drawn under bars, quiet neutral stroke) */}
          {dependencies.map((dep) => (
            <path
              key={dep.key}
              className="gantt__dep-path"
              d={dep.d}
              markerEnd="url(#dep-arrowhead)"
            />
          ))}

          {/* Task bars */}
          {tasks.map((task) => {
            const sched = scheduleById.get(task.id);
            const bar = bars.get(task.id);
            if (!sched || !bar) return null;

            const isDragging = drag?.taskId === task.id;
            const width = isDragging ? drag!.previewDurationDays * dayWidth : bar.w;
            const isChanged = changedIds.includes(task.id);
            const barH = bar.h * BAR_HEIGHT_RATIO;
            const barY = bar.y + (bar.h - barH) / 2;
            const renderWidth = Math.max(width, MIN_BAR_WIDTH);
            const labelInside = renderWidth > 44;

            return (
              <g key={task.id}>
                <rect
                  className="gantt__bar"
                  data-testid="task-bar"
                  data-id={task.id}
                  data-critical={sched.is_critical}
                  data-assignee={task.assignee}
                  data-start={sched.start}
                  data-end={sched.end}
                  x={bar.x}
                  y={barY}
                  width={renderWidth}
                  height={barH}
                  rx={2}
                  filter="url(#bar-shadow)"
                  onClick={() => onSelectTask?.(task.id)}
                />
                <rect
                  className="gantt__bar-outline"
                  data-changed={isChanged}
                  x={bar.x - 2}
                  y={barY - 2}
                  width={renderWidth + 4}
                  height={barH + 4}
                  rx={4}
                />
                {labelInside ? (
                  <text
                    className="gantt__bar-label"
                    data-critical={sched.is_critical}
                    x={bar.x + 8}
                    y={barY + barH / 2 + 3}
                  >
                    {task.duration_days}Д
                  </text>
                ) : (
                  <text
                    className="gantt__bar-label gantt__bar-label--outside"
                    x={bar.x + renderWidth + 6}
                    y={barY + barH / 2 + 3}
                  >
                    {task.duration_days}Д
                  </text>
                )}
                <rect
                  className="gantt__resize-handle"
                  x={bar.x + width - 6}
                  y={barY}
                  width={12}
                  height={barH}
                  onPointerDown={handleResizeStart(task, sched)}
                />
              </g>
            );
          })}

          {/* Two-tier timeline header, drawn last so it sits above grid/bars while scrolling */}
          <g className="gantt__timeline-header">
            <rect className="gantt__header-bg" x={0} y={0} width={chartWidth} height={HEADER_H} />
            {months.map((span) => (
              <g key={span.label + span.x}>
                <text className="gantt__month-label" x={span.centerX} y={HEADER_SPLIT / 2 + 1}>
                  {span.label}
                </text>
                {span.x > 0 && (
                  <line
                    className="gantt__month-divider"
                    x1={span.x}
                    x2={span.x}
                    y1={0}
                    y2={HEADER_H}
                  />
                )}
              </g>
            ))}
            <line className="gantt__header-rule" x1={0} x2={chartWidth} y1={HEADER_SPLIT} y2={HEADER_SPLIT} />
            {ticks.map((tick) => (
              <g key={`tick-${tick.x}`}>
                <line
                  className="gantt__tick-mark"
                  x1={tick.x}
                  x2={tick.x}
                  y1={HEADER_SPLIT}
                  y2={HEADER_H}
                />
                <text className="gantt__grid-label" x={tick.x + 6} y={HEADER_H - 7}>
                  {tick.label}
                </text>
              </g>
            ))}
            {todayX <= chartWidth && (
              <circle className="gantt__today-pin" cx={todayX} cy={HEADER_SPLIT / 2} r={3} />
            )}
          </g>
        </svg>
      </div>
    </section>
  );
}
