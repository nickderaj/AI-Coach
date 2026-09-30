import { describe, expect, it } from "vitest";

import type { WorkoutLike } from "./stats";
import {
  durationMinutes,
  estimatedOneRepMax,
  personalRecords,
  sessionStats,
  thisWeek,
  weekStart,
  weekStreak,
  weeklyTotals,
} from "./stats";

// Tests run in Pacific/Auckland (UTC+13 in late September): see vite.config.ts.
const NOW = new Date("2026-09-30T08:00:00Z"); // Wed 30 Sept, 21:00 local

function workout(started_at: string, volume_kg = 100, ended_at: string | null = null): WorkoutLike {
  return { started_at, ended_at, volume_kg };
}

describe("weekStart", () => {
  it.each([
    ["2026-09-30T08:00:00Z", "2026-09-28"], // Wednesday
    ["2026-09-27T12:00:00Z", "2026-09-28"], // Monday 01:00 local
    ["2026-09-27T10:59:00Z", "2026-09-21"], // Sunday 23:59 local
    ["2026-10-04T10:00:00Z", "2026-09-28"], // Sunday 23:00 local, same week
  ])("%s starts on Monday %s (local)", (iso, monday) => {
    const start = weekStart(new Date(iso));
    expect(start.getDay()).toBe(1);
    expect([start.getFullYear(), start.getMonth() + 1, start.getDate(), start.getHours()]).toEqual([
      ...monday.split("-").map(Number),
      0,
    ]);
  });
});

describe("weeklyTotals", () => {
  it("buckets workouts into the last N weeks, oldest first", () => {
    const totals = weeklyTotals(
      [
        workout("2026-09-29T00:00:00Z", 1000), // this week
        workout("2026-09-28T00:00:00Z", 500), // this week
        workout("2026-09-22T00:00:00Z", 300), // last week (Tue 22 Sept local)
        workout("2026-07-01T00:00:00Z", 999), // too old
      ],
      3,
      NOW,
    );

    expect(totals.map((t) => [t.start.getDate(), t.workouts, t.volume])).toEqual([
      [14, 0, 0],
      [21, 1, 300],
      [28, 2, 1500],
    ]);
  });
});

describe("thisWeek", () => {
  it("counts only the week containing now", () => {
    const week = thisWeek(
      [workout("2026-09-29T00:00:00Z", 1000), workout("2026-09-22T00:00:00Z", 300)],
      NOW,
    );

    expect([week.start.getDate(), week.workouts, week.volume]).toEqual([28, 1, 1000]);
  });

  it("is empty without workouts", () => {
    expect(thisWeek([], NOW)).toMatchObject({ workouts: 0, volume: 0 });
  });
});

describe("weekStreak", () => {
  it("counts consecutive weeks including this one", () => {
    const workouts = ["2026-09-29", "2026-09-22", "2026-09-15", "2026-09-01"].map((d) =>
      workout(`${d}T00:00:00Z`),
    );

    expect(weekStreak(workouts, NOW)).toBe(3);
  });

  it("does not break the streak for a week that is not over yet", () => {
    const workouts = ["2026-09-22", "2026-09-15"].map((d) => workout(`${d}T00:00:00Z`));

    expect(weekStreak(workouts, NOW)).toBe(2);
  });

  it("is zero after a missed week", () => {
    expect(weekStreak([workout("2026-09-08T00:00:00Z")], NOW)).toBe(0);
    expect(weekStreak([], NOW)).toBe(0);
  });
});

describe("durationMinutes", () => {
  it("rounds to whole minutes", () => {
    expect(durationMinutes(workout("2026-09-29T10:00:00Z", 0, "2026-09-29T11:12:31Z"))).toBe(73);
  });

  it("is null while unfinished", () => {
    expect(durationMinutes(workout("2026-09-29T10:00:00Z"))).toBeNull();
  });
});

describe("estimatedOneRepMax", () => {
  it.each([
    [{ reps: 1, load_kg: 100, duration_s: null }, 100],
    [{ reps: 10, load_kg: 60, duration_s: null }, 80],
    [{ reps: 0, load_kg: 60, duration_s: null }, null],
    [{ reps: null, load_kg: 60, duration_s: null }, null],
    [{ reps: 8, load_kg: null, duration_s: null }, null],
  ])("%j -> %s", (set, expected) => {
    expect(estimatedOneRepMax(set)).toBe(expected);
  });
});

describe("sessionStats and personalRecords", () => {
  const monday = [
    { reps: 10, load_kg: 60, duration_s: null },
    { reps: 6, load_kg: 70, duration_s: null },
  ];
  const friday = [
    { reps: 12, load_kg: 50, duration_s: null },
    { reps: null, load_kg: null, duration_s: 45 },
  ];

  it("summarises one session", () => {
    expect(sessionStats(monday)).toEqual({
      heaviest: 70,
      oneRepMax: 84,
      volume: 1020,
      mostReps: 10,
      longest: null,
    });
  });

  it("takes the best of each number across sessions", () => {
    expect(personalRecords([monday, friday])).toEqual({
      heaviest: 70,
      oneRepMax: 84,
      volume: 1020,
      mostReps: 12,
      longest: 45,
    });
  });

  it("has nothing to report without sessions", () => {
    expect(personalRecords([])).toEqual({
      heaviest: null,
      oneRepMax: null,
      volume: 0,
      mostReps: null,
      longest: null,
    });
  });
});
