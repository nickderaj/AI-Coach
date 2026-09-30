/** Training statistics derived on the device from API data (all pure). */

export interface SetLike {
  reps: number | null;
  load_kg: number | null;
  duration_s: number | null;
}

export interface WorkoutLike {
  started_at: string;
  ended_at: string | null;
  volume_kg: number;
}

export interface WeekTotal {
  start: Date;
  workouts: number;
  volume: number;
}

/**
 * Monday 00:00 (device time) of the week containing `moment`.
 *
 * @internal Exported for tests; screens use the weekly helpers below.
 */
export function weekStart(moment: Date): Date {
  const start = new Date(moment.getFullYear(), moment.getMonth(), moment.getDate());
  const daysSinceMonday = (start.getDay() + 6) % 7;
  start.setDate(start.getDate() - daysSinceMonday);
  return start;
}

function addWeeks(date: Date, weeks: number): Date {
  const moved = new Date(date);
  moved.setDate(moved.getDate() + weeks * 7);
  return moved;
}

/** Workouts and volume for each of the `weeks` weeks ending with the week of `now`, oldest first. */
export function weeklyTotals(workouts: WorkoutLike[], weeks: number, now: Date): WeekTotal[] {
  const current = weekStart(now);
  const totals = Array.from({ length: weeks }, (_, index) => ({
    start: addWeeks(current, index - weeks + 1),
    workouts: 0,
    volume: 0,
  }));
  for (const workout of workouts) {
    const start = weekStart(new Date(workout.started_at)).getTime();
    const total = totals.find((week) => week.start.getTime() === start);
    if (total !== undefined) {
      total.workouts += 1;
      total.volume += workout.volume_kg;
    }
  }
  return totals;
}

/** Workouts and volume in the week containing `now`. */
export function thisWeek(workouts: WorkoutLike[], now: Date): WeekTotal {
  const start = weekStart(now);
  const inWeek = workouts.filter(
    (workout) => weekStart(new Date(workout.started_at)).getTime() === start.getTime(),
  );
  return {
    start,
    workouts: inWeek.length,
    volume: inWeek.reduce((sum, workout) => sum + workout.volume_kg, 0),
  };
}

/**
 * Consecutive weeks with at least one workout, counting back from this week.
 * A week without a workout yet does not break the streak until it is over.
 */
export function weekStreak(workouts: WorkoutLike[], now: Date): number {
  const trained = new Set(workouts.map((w) => weekStart(new Date(w.started_at)).getTime()));
  let week = weekStart(now);
  if (!trained.has(week.getTime())) {
    week = addWeeks(week, -1);
  }
  let streak = 0;
  while (trained.has(week.getTime())) {
    streak += 1;
    week = addWeeks(week, -1);
  }
  return streak;
}

/** Whole minutes between start and end, or null while unfinished. */
export function durationMinutes(workout: WorkoutLike): number | null {
  if (workout.ended_at === null) {
    return null;
  }
  const ms = new Date(workout.ended_at).getTime() - new Date(workout.started_at).getTime();
  return Math.round(ms / 60_000);
}

interface SessionLike {
  workout_id: number;
  position: number;
  started_at: string;
}

/**
 * Sessions oldest first. The API lists workouts newest first but repeated blocks
 * within one workout in position order, so a plain reverse would flip those.
 */
export function chronological<T extends SessionLike>(sessions: readonly T[]): T[] {
  return [...sessions].sort(
    (a, b) =>
      new Date(a.started_at).getTime() - new Date(b.started_at).getTime() ||
      a.workout_id - b.workout_id ||
      a.position - b.position,
  );
}

/**
 * Estimated one-rep max (Epley); a single rep is its own max. Null without load and reps.
 *
 * @internal Exported for tests; screens use `sessionStats` and `personalRecords`.
 */
export function estimatedOneRepMax(set: SetLike): number | null {
  if (set.load_kg === null || set.reps === null || set.reps < 1) {
    return null;
  }
  return set.reps === 1 ? set.load_kg : set.load_kg * (1 + set.reps / 30);
}

function maximum(values: (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length === 0 ? null : Math.max(...present);
}

export interface SessionStats {
  heaviest: number | null;
  oneRepMax: number | null;
  volume: number;
  mostReps: number | null;
  longest: number | null;
}

/** Headline numbers for one session (the sets of one exercise in one workout). */
export function sessionStats(sets: SetLike[]): SessionStats {
  return {
    heaviest: maximum(sets.map((set) => set.load_kg)),
    oneRepMax: maximum(sets.map(estimatedOneRepMax)),
    volume: sets.reduce((sum, set) => sum + (set.reps ?? 0) * (set.load_kg ?? 0), 0),
    mostReps: maximum(sets.map((set) => set.reps)),
    longest: maximum(sets.map((set) => set.duration_s)),
  };
}

/** Best of each headline number across sessions (personal records). */
export function personalRecords(sessions: SetLike[][]): SessionStats {
  const stats = sessions.map(sessionStats);
  const best = (pick: (s: SessionStats) => number | null): number | null =>
    maximum(stats.map(pick));
  return {
    heaviest: best((s) => s.heaviest),
    oneRepMax: best((s) => s.oneRepMax),
    volume: maximum(stats.map((s) => s.volume)) ?? 0,
    mostReps: best((s) => s.mostReps),
    longest: best((s) => s.longest),
  };
}
