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
 * `rowHeight` is the full row height; the bar itself is inset within the row
 * (handled by the caller/component via a fixed bar height) — this helper
 * returns the row's vertical band (y, h) plus the bar's horizontal span.
 */
export function taskBar(
  scheduled: Pick<Scheduled, 'start' | 'end'>,
  rowIndex: number,
  rowHeight: number,
  dayWidth: number,
  projectStartISO: string,
): Bar {
  const x = dateToX(scheduled.start, projectStartISO, dayWidth);
  const endX = dateToX(scheduled.end, projectStartISO, dayWidth);
  return {
    x,
    y: rowIndex * rowHeight,
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
