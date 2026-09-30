import type { Measure, SetEntry } from "./api";

// A fixed locale keeps the layout predictable; times are shown in the phone's zone.
const LOCALE = "en-GB";
const DAY = new Intl.DateTimeFormat(LOCALE, { weekday: "short", day: "numeric", month: "short" });
const DAY_WITH_YEAR = new Intl.DateTimeFormat(LOCALE, {
  day: "numeric",
  month: "short",
  year: "numeric",
});
const TIME = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" });

export function formatDay(iso: string): string {
  return DAY.format(new Date(iso));
}

export function formatDate(iso: string): string {
  return DAY_WITH_YEAR.format(new Date(iso));
}

export function formatTime(iso: string): string {
  return TIME.format(new Date(iso));
}

function formatNumber(value: number): string {
  return String(Number(value.toFixed(2)));
}

/** One set as it would be written in a training log, e.g. "12 × 22.5 kg" or "50 s". */
export function formatSet(set: SetEntry, measure: Measure): string {
  if (measure === "seconds" && set.duration_s !== null) {
    return `${formatNumber(set.duration_s)} s`;
  }
  const reps = set.reps === null ? "?" : String(set.reps);
  if (set.load_kg === null) {
    return `${reps} reps`;
  }
  return `${reps} × ${formatNumber(set.load_kg)} kg`;
}

export function plural(count: number, noun: string): string {
  return `${String(count)} ${noun}${count === 1 ? "" : "s"}`;
}

export function formatLoad(kg: number): string {
  return `${formatNumber(kg)} kg`;
}
