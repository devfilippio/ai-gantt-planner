/**
 * Pure geometry helpers for the SVG Gantt chart. No React, no DOM — just
 * date/day math so it stays trivially unit-testable and inspectable.
 *
 * Dates are calendar days (no time-of-day component). We parse ISO date
 * strings ("YYYY-MM-DD") as UTC midnight so day-diff math is never thrown
 * off by the host machine's timezone or DST transitions.
 */
import type { Scheduled } from '../types';

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/**
 * Fixed "today" reference for the demo: project_start + 12 calendar days.
 * The seed plan's `project_start` (2026-05-05) is itself a fixed constant,
 * so anchoring "today" to it (rather than the real wall-clock date) keeps
 * the chart's most interesting moment — mid-build, roughly halfway through
 * the 7-task "Запуск лендинга" plan — reproducible across every screenshot,
 * demo, and Playwright run. Shared between GanttChart (today line) and
 * TaskModal (mini timeline's today marker) so both surfaces agree.
 */
export const TODAY_OFFSET_DAYS = 12;

const RU_MONTHS = [
  'ЯНВ',
  'ФЕВ',
  'МАР',
  'АПР',
  'МАЙ',
  'ИЮН',
  'ИЮЛ',
  'АВГ',
  'СЕН',
  'ОКТ',
  'НОЯ',
  'ДЕК',
];

/** Parse an ISO "YYYY-MM-DD" date string as a UTC-midnight timestamp (ms). */
function parseISODate(dateISO: string): number {
  const [y, m, d] = dateISO.split('-').map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Whole calendar days between two ISO dates (b - a), can be negative. */
export function daysBetween(aISO: string, bISO: string): number {
  return Math.round((parseISODate(bISO) - parseISODate(aISO)) / MS_PER_DAY);
}

/** Format a UTC timestamp as "05 МАЙ" (day + short Russian month, uppercase). */
function formatRuDay(ts: number): string {
  const date = new Date(ts);
  const day = String(date.getUTCDate()).padStart(2, '0');
  const month = RU_MONTHS[date.getUTCMonth()];
  return `${day} ${month}`;
}

/**
 * Horizontal pixel offset of a calendar date from the project start.
 * `dayWidth` is the pixel width of one calendar day at the current zoom.
 */
export function dateToX(dateISO: string, projectStartISO: string, dayWidth: number): number {
  return daysBetween(projectStartISO, dateISO) * dayWidth;
}

export interface Bar {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Compute the pixel rect for a scheduled task's bar.
 * `rowHeight` is the full row height; `headerHeight` offsets every row band
 * below the chart's timeline header so row 1 starts at y = headerHeight
 * (matching a `headerHeight`-tall spacer in the left column). This helper
 * returns the row's vertical band (y, h) plus the bar's horizontal span; the
 * caller derives the actual bar rect (vertically centered, shorter than the
 * row) from this band.
 */
export function taskBar(
  scheduled: Pick<Scheduled, 'start' | 'end'>,
  rowIndex: number,
  rowHeight: number,
  dayWidth: number,
  projectStartISO: string,
  headerHeight = 0,
): Bar {
  const x = dateToX(scheduled.start, projectStartISO, dayWidth);
  const endX = dateToX(scheduled.end, projectStartISO, dayWidth);
  return {
    x,
    y: rowIndex * rowHeight + headerHeight,
    w: Math.max(endX - x, 1),
    h: rowHeight,
  };
}

export interface WeekTick {
  x: number;
  label: string;
}

export interface DayTick {
  x: number;
  /** 2-digit day-of-month, e.g. "05". */
  label: string;
  isWeekend: boolean;
  isWeekStart: boolean;
}

/**
 * Per-day tick positions for the day-zoom lower header strip, one entry per
 * calendar day in [projectStart, projectStart + totalDays). Used to print a
 * numeral in every day cell and to drive weekend-column shading — unlike
 * `weekTicks` (week boundaries only, for the week-zoom header).
 *
 * `isWeekStart` flags Mondays (ISO week start) so the day grid can draw a
 * slightly stronger boundary line there, matching frappe-gantt's convention.
 */
export function dayTicks(projectStartISO: string, totalDays: number, dayWidth: number): DayTick[] {
  const startTs = parseISODate(projectStartISO);
  const ticks: DayTick[] = [];
  for (let day = 0; day < totalDays; day += 1) {
    const ts = startTs + day * MS_PER_DAY;
    const date = new Date(ts);
    const dow = date.getUTCDay(); // 0 = Sunday, 6 = Saturday
    ticks.push({
      x: day * dayWidth,
      label: String(date.getUTCDate()).padStart(2, '0'),
      isWeekend: dow === 0 || dow === 6,
      isWeekStart: dow === 1,
    });
  }
  return ticks;
}

/**
 * Vertical gridline positions for each week boundary, starting at the
 * project start, spanning `totalDays` calendar days.
 */
export function weekTicks(
  projectStartISO: string,
  totalDays: number,
  dayWidth: number,
): WeekTick[] {
  const startTs = parseISODate(projectStartISO);
  const ticks: WeekTick[] = [];
  for (let day = 0; day <= totalDays; day += 7) {
    const ts = startTs + day * MS_PER_DAY;
    ticks.push({ x: day * dayWidth, label: formatRuDay(ts) });
  }
  return ticks;
}

export interface MonthSpan {
  /** Left pixel edge of this month's portion of the chart. */
  x: number;
  /** Pixel width of this month's portion of the chart (may be partial at the chart's edges). */
  w: number;
  /** Horizontal center of the span — where the month label should be drawn. */
  centerX: number;
  /** e.g. "МАЙ 2026". */
  label: string;
}

/**
 * Contiguous month spans covering `totalDays` calendar days starting at
 * `projectStartISO`, for the upper strip of the two-tier timeline header.
 * Each month prints its label once, centered over its own (possibly partial)
 * range, rather than once per week tick.
 *
 * Manual check: projectStart="2026-05-05", totalDays=29 → spans
 * [МАЙ 2026: day 0..26 (x=0, w=26*dayWidth)], [ИЮНЬ 2026: day 26..29 (x=26*dayWidth, w=3*dayWidth)].
 * (May has 31 days; 2026-05-05 + 26 days = 2026-05-31, so May's span covers
 * days 0..26 — the 26 remaining days of May — and June picks up from day 26.)
 */
const RU_MONTHS_FULL = [
  'ЯНВАРЬ',
  'ФЕВРАЛЬ',
  'МАРТ',
  'АПРЕЛЬ',
  'МАЙ',
  'ИЮНЬ',
  'ИЮЛЬ',
  'АВГУСТ',
  'СЕНТЯБРЬ',
  'ОКТЯБРЬ',
  'НОЯБРЬ',
  'ДЕКАБРЬ',
];

export function monthSpans(
  projectStartISO: string,
  totalDays: number,
  dayWidth: number,
): MonthSpan[] {
  const startTs = parseISODate(projectStartISO);
  const spans: MonthSpan[] = [];
  let dayCursor = 0;

  while (dayCursor < totalDays) {
    const ts = startTs + dayCursor * MS_PER_DAY;
    const date = new Date(ts);
    const year = date.getUTCFullYear();
    const month = date.getUTCMonth();
    const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    const dayOfMonth = date.getUTCDate();
    const daysRemainingInMonth = daysInMonth - dayOfMonth + 1;
    const spanDays = Math.min(daysRemainingInMonth, totalDays - dayCursor);

    const x = dayCursor * dayWidth;
    const w = spanDays * dayWidth;
    spans.push({
      x,
      w,
      centerX: x + w / 2,
      label: `${RU_MONTHS_FULL[month]} ${year}`,
    });

    dayCursor += spanDays;
  }

  return spans;
}

/** Lowercase genitive-case month names ("12 МАЯ" reads "12 мая") for
 * human-readable date ranges — Russian date phrases inflect the month noun
 * to the genitive case ("мая", not the nominative "май" used in headers). */
const RU_MONTHS_GENITIVE = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря',
];

/** Format a single ISO date as "12 мая 2026" (day, genitive month, year). */
function formatRuDateSingle(dateISO: string): string {
  const ts = parseISODate(dateISO);
  const date = new Date(ts);
  const day = date.getUTCDate();
  const month = RU_MONTHS_GENITIVE[date.getUTCMonth()];
  const year = date.getUTCFullYear();
  return `${day} ${month} ${year}`;
}

/**
 * Human-readable Russian date range for the task modal, e.g.
 * "12 мая → 18 мая 2026". The year is printed once, on the end date, unless
 * the range spans a year boundary (then both dates carry their own year).
 */
export function formatRuDateLong(startISO: string, endISO: string): string {
  const startTs = parseISODate(startISO);
  const endTs = parseISODate(endISO);
  const startYear = new Date(startTs).getUTCFullYear();
  const endYear = new Date(endTs).getUTCFullYear();

  if (startYear !== endYear) {
    return `${formatRuDateSingle(startISO)} → ${formatRuDateSingle(endISO)}`;
  }

  const startDate = new Date(startTs);
  const startDay = startDate.getUTCDate();
  const startMonth = RU_MONTHS_GENITIVE[startDate.getUTCMonth()];
  return `${startDay} ${startMonth} → ${formatRuDateSingle(endISO)}`;
}

/** Arc radius for the rounded elbow turns in `dependencyPath`. */
const ELBOW_RADIUS = 5;
/** Horizontal run out of the source bar / into the target bar before turning. */
const ELBOW_INDENT = 12;

/**
 * Build a rounded-corner SVG path from a list of orthogonal waypoints (each
 * segment between consecutive points must be purely horizontal or purely
 * vertical). Every interior corner is rounded to radius `r` (clamped so it
 * never eats more than half of either adjacent segment) using a quadratic
 * Bezier, which — unlike an elliptical arc command — needs no sweep-flag
 * bookkeeping: the same `Q cx,cy ex,ey` shape works regardless of turn
 * direction, so this is much easier to get right (and keep right) than
 * hand-deriving `A` sweep flags per corner.
 */
function roundedOrthogonalPath(points: { x: number; y: number }[], r: number): string {
  if (points.length < 2) return '';
  if (points.length === 2) {
    return `M ${points[0].x} ${points[0].y} L ${points[1].x} ${points[1].y}`;
  }

  const parts: string[] = [`M ${points[0].x} ${points[0].y}`];
  for (let i = 1; i < points.length - 1; i += 1) {
    const prev = points[i - 1];
    const curr = points[i];
    const next = points[i + 1];

    const segIn = Math.min(Math.hypot(curr.x - prev.x, curr.y - prev.y) / 2, r);
    const segOut = Math.min(Math.hypot(next.x - curr.x, next.y - curr.y) / 2, r);
    const rr = Math.min(segIn, segOut);

    const inX = curr.x - Math.sign(curr.x - prev.x) * rr;
    const inY = curr.y - Math.sign(curr.y - prev.y) * rr;
    const outX = curr.x + Math.sign(next.x - curr.x) * rr;
    const outY = curr.y + Math.sign(next.y - curr.y) * rr;

    parts.push(`L ${inX} ${inY}`, `Q ${curr.x} ${curr.y} ${outX} ${outY}`);
  }
  const last = points[points.length - 1];
  parts.push(`L ${last.x} ${last.y}`);
  return parts.join(' ');
}

/**
 * Frappe-gantt-style orthogonal ("elbow") dependency path from a predecessor
 * bar's right edge to a successor bar's left edge, with small rounded
 * corners instead of sharp 90° turns. Two routing branches:
 *
 * - Normal case (target starts after the source's indent clears): exit
 *   right-mid → short horizontal run → turn → vertical → turn → horizontal
 *   into the target's left edge (a simple 4-point Z-elbow).
 * - Overlap case (target starts before the source has cleared its own
 *   indent — parallel/overlapping bars): a direct elbow would cut back
 *   across the source (or target) bar body, so instead the line dips into
 *   the gap between rows (the row boundary nearest the source, using
 *   `rowHeight`) and travels there before turning down/up into the target's
 *   left edge — never crossing a bar.
 *
 * `rowHeight` defaults to the bar's own height (h), a safe fallback when
 * rows are tightly packed around their bars.
 */
export function dependencyPath(fromBar: Bar, toBar: Bar, rowHeight?: number): string {
  const startX = fromBar.x + fromBar.w;
  const startY = fromBar.y + fromBar.h / 2;
  const endX = toBar.x;
  const endY = toBar.y + toBar.h / 2;
  const rh = rowHeight ?? fromBar.h;
  const r = ELBOW_RADIUS;

  if (Math.abs(endY - startY) < 0.5) {
    // Same row (rare, e.g. equal-duration parallel tasks) — a straight line.
    return `M ${startX} ${startY} L ${endX} ${endY}`;
  }

  // Normal case: enough horizontal room to run out of the source, turn
  // toward the target's row, and turn again into its left edge. Requires
  // some slack past the indent so the two rounded corners (source-exit turn
  // and target-entry turn) don't need to overlap each other.
  const midX = startX + ELBOW_INDENT;
  if (endX >= midX + r * 2) {
    return roundedOrthogonalPath(
      [
        { x: startX, y: startY },
        { x: midX, y: startY },
        { x: midX, y: endY },
        { x: endX, y: endY },
      ],
      r,
    );
  }

  // Overlap case: the target's left edge sits before the source can turn
  // toward it — route through the gap between rows instead of straight
  // across, so the line never crosses a bar body.
  const goingDown = endY > startY;
  const gapY = goingDown ? fromBar.y + rh : fromBar.y;
  const approachX = endX - ELBOW_INDENT;

  return roundedOrthogonalPath(
    [
      { x: startX, y: startY },
      { x: midX, y: startY },
      { x: midX, y: gapY },
      { x: approachX, y: gapY },
      { x: approachX, y: endY },
      { x: endX, y: endY },
    ],
    r,
  );
}
