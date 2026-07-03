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

/**
 * Smooth cubic-bezier SVG path from a predecessor bar's right edge to a
 * successor bar's left edge — the classic Gantt "S-curve" dependency arrow.
 * The control points pull horizontally so the curve reads left-to-right
 * regardless of how far apart the rows are vertically.
 */
export function dependencyPath(fromBar: Bar, toBar: Bar): string {
  const startX = fromBar.x + fromBar.w;
  const startY = fromBar.y + fromBar.h / 2;
  const endX = toBar.x;
  const endY = toBar.y + toBar.h / 2;

  const dx = Math.max(Math.abs(endX - startX) * 0.5, 24);
  const c1x = startX + dx;
  const c1y = startY;
  const c2x = endX - dx;
  const c2y = endY;

  return `M ${startX} ${startY} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${endX} ${endY}`;
}
