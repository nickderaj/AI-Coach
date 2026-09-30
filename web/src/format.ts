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
export function formatSet(
  set: Pick<SetEntry, "reps" | "load_kg" | "duration_s">,
  measure: Measure,
): string {
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

const WHOLE = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });

/** A whole number with separators, e.g. "9,860". */
export function formatWhole(value: number): string {
  return WHOLE.format(value);
}

/** A total volume, e.g. "9,860 kg". */
export function formatVolume(kg: number): string {
  return `${formatWhole(kg)} kg`;
}

/** A duration in minutes, e.g. "48 min" or "1 h 12 min". */
export function formatMinutes(minutes: number): string {
  if (minutes < 60) {
    return `${String(minutes)} min`;
  }
  const rest = minutes % 60;
  const hours = `${String(Math.floor(minutes / 60))} h`;
  return rest === 0 ? hours : `${hours} ${String(rest)} min`;
}

const SHORT_DAY = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short" });

/** A compact date for chart axes, e.g. "29 Sept". */
export function formatShortDate(value: Date | string): string {
  return SHORT_DAY.format(typeof value === "string" ? new Date(value) : value);
}

/** Part of the day a workout started in, for titles like "Morning workout". */
export function partOfDay(iso: string): string {
  const hour = new Date(iso).getHours();
  if (hour < 12) {
    return "Morning";
  }
  return hour < 17 ? "Afternoon" : "Evening";
}

/** A running clock: "0:05", "12:34", "1:02:03". Negative durations show as zero. */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours === 0
    ? `${String(minutes)}:${seconds}`
    : `${String(hours)}:${String(minutes).padStart(2, "0")}:${seconds}`;
}
