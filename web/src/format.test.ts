import { describe, expect, it } from "vitest";

import type { SetEntry } from "./api";
import {
  formatDate,
  formatDay,
  formatLoad,
  formatMinutes,
  formatSet,
  formatShortDate,
  formatTime,
  formatVolume,
  formatWhole,
  partOfDay,
  plural,
} from "./format";

const base: SetEntry = {
  set_number: 1,
  reps: 12,
  load_kg: 22.5,
  duration_s: null,
  rpe: null,
  notes: null,
  client_id: null,
};

describe("formatSet", () => {
  it("writes reps × load", () => {
    expect(formatSet(base, "reps")).toBe("12 × 22.5 kg");
  });

  it("drops trailing zeros and float noise from loads", () => {
    expect(formatSet({ ...base, load_kg: 20 }, "reps")).toBe("12 × 20 kg");
    expect(formatSet({ ...base, load_kg: 0.1 + 0.2 }, "reps")).toBe("12 × 0.3 kg");
  });

  it("writes bodyweight sets as reps", () => {
    expect(formatSet({ ...base, load_kg: null }, "reps")).toBe("12 reps");
  });

  it("marks unknown reps", () => {
    expect(formatSet({ ...base, reps: null }, "reps")).toBe("? × 22.5 kg");
  });

  it("writes timed sets in seconds", () => {
    expect(formatSet({ ...base, reps: null, load_kg: null, duration_s: 50 }, "seconds")).toBe(
      "50 s",
    );
  });

  it("falls back to reps when a timed exercise has no duration", () => {
    expect(formatSet({ ...base, load_kg: null }, "seconds")).toBe("12 reps");
  });
});

describe("dates", () => {
  // Tests run at Pacific/Auckland (UTC+13 in late September) — see vite.config.ts.
  const late = "2026-09-28T11:30:59+00:00";

  it("formats in the device's zone", () => {
    expect(formatDay(late)).toBe("Tue 29 Sept");
    expect(formatTime(late)).toBe("00:30");
    expect(formatDate(late)).toBe("29 Sept 2026");
  });
});

describe("plural and load", () => {
  it("pluralises", () => {
    expect(plural(1, "set")).toBe("1 set");
    expect(plural(0, "set")).toBe("0 sets");
    expect(plural(21, "set")).toBe("21 sets");
  });

  it("formats loads", () => {
    expect(formatLoad(82.5)).toBe("82.5 kg");
  });
});

describe("new formatters", () => {
  it("formats whole numbers with separators", () => {
    expect(formatWhole(12345.6)).toBe("12,346");
  });

  it("formats volume with separators", () => {
    expect(formatVolume(9860)).toBe("9,860 kg");
    expect(formatVolume(12.4)).toBe("12 kg");
  });

  it("formats durations", () => {
    expect(formatMinutes(0)).toBe("0 min");
    expect(formatMinutes(59)).toBe("59 min");
    expect(formatMinutes(60)).toBe("1 h");
    expect(formatMinutes(72)).toBe("1 h 12 min");
  });

  it("formats short dates from strings and dates", () => {
    expect(formatShortDate("2026-09-28T11:30:59+00:00")).toBe("29 Sept");
    expect(formatShortDate(new Date(2026, 0, 5))).toBe("5 Jan");
  });

  it.each([
    ["2026-09-29T10:59:00+13:00", "Morning"],
    ["2026-09-29T11:59:00+13:00", "Morning"],
    ["2026-09-29T12:00:00+13:00", "Afternoon"],
    ["2026-09-29T16:59:00+13:00", "Afternoon"],
    ["2026-09-29T17:00:00+13:00", "Evening"],
  ])("names the part of day for %s", (iso, part) => {
    expect(partOfDay(iso)).toBe(part);
  });
});
