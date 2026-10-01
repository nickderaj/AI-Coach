import { describe, expect, it } from "vitest";

import type { SetEntry, WorkoutDetail } from "../api";
import { UPPER } from "../test/today";
import {
  blockLabel,
  groupBlocks,
  restAfter,
  todayDraft,
  restored,
  toSecond,
  typedOf,
  addBlock,
  addSet,
  deleteSetWrite,
  discardWrite,
  draftFromServer,
  draftSchema,
  finishWrite,
  loggedSets,
  newDraft,
  parseAmount,
  previousFrom,
  removeBlock,
  removeSet,
  setWrite,
  startWrite,
  updateSet,
  valuesOf,
} from "./draft";
import type { Draft, DraftExercise, DraftSet, Previous } from "./draft";

const START = new Date("2026-09-30T08:00:00Z");
const BENCH: DraftExercise = { id: 7, name: "Bench Press", measure: "reps", equipment: "barbell" };
const HANG: DraftExercise = { id: 9, name: "Dead Hang", measure: "seconds", equipment: null };

const row = (values: Partial<DraftSet> = {}): DraftSet => ({
  id: "s",
  kg: "",
  reps: "",
  seconds: "",
  rpe: "",
  logged: null,
  ...values,
});

const BENCH_8x60 = { kg: "60", reps: "8", seconds: "", rpe: "" };

function withBench(previous = [{ reps: 8, load_kg: 60, duration_s: null }]): Draft {
  return addBlock(newDraft("w", START), { block: "b", set: "s1" }, BENCH, previous);
}

function block(draft: Draft, index = 0): Draft["blocks"][number] {
  const found = draft.blocks[index];
  if (found === undefined) {
    throw new Error("no such block");
  }
  return found;
}

describe("parseAmount", () => {
  it.each([
    ["22.5", 22.5],
    ["22,5", 22.5],
    [" 8 ", 8],
    ["0", 0],
    ["", null],
    ["  ", null],
    ["abc", null],
    ["-5", null],
    ["Infinity", null],
  ])("%j -> %s", (text, value) => {
    expect(parseAmount(text)).toBe(value);
  });
});

describe("valuesOf", () => {
  it.each([
    [row({ kg: "60", reps: "8" }), { reps: 8, load_kg: 60, duration_s: null, rpe: null }],
    [row({ reps: "12" }), { reps: 12, load_kg: null, duration_s: null, rpe: null }],
    [row({ kg: "60" }), null],
    [row({ kg: "60", reps: "8.5" }), null],
    [row({ kg: "sixty", reps: "8" }), null],
  ])("reps: %j", (set, values) => {
    expect(valuesOf(set, "reps")).toEqual(values);
  });

  it.each([
    [row({ seconds: "45" }), { reps: null, load_kg: null, duration_s: 45, rpe: null }],
    [row({ kg: "10", seconds: "30.5" }), { reps: null, load_kg: 10, duration_s: 30.5, rpe: null }],
    [row({ reps: "8" }), null],
  ])("seconds: %j", (set, values) => {
    expect(valuesOf(set, "seconds")).toEqual(values);
  });
});

describe("valuesOf with RPE", () => {
  it.each([
    ["8", 8],
    [" 10 ", 10],
    ["1", 1],
    ["", null],
  ])("logs RPE %j as %s", (rpe, value) => {
    expect(valuesOf(row({ reps: "5", rpe }), "reps")?.rpe).toBe(value);
    expect(valuesOf(row({ seconds: "30", rpe }), "seconds")?.rpe).toBe(value);
  });

  it.each(["0", "11", "7.5", "hard"])("will not log RPE %j", (rpe) => {
    expect(valuesOf(row({ reps: "5", rpe }), "reps")).toBeNull();
  });
});

describe("editing a draft", () => {
  it("starts at a whole second, as the server keeps it", () => {
    expect(newDraft("w", new Date("2026-09-30T08:00:00.987Z")).started_at).toBe(
      "2026-09-30T08:00:00.000Z",
    );
    expect(toSecond("2026-09-30T08:00:00.987Z")).toBe(toSecond("2026-09-30T08:00:00+00:00"));
  });

  it("starts empty", () => {
    expect(newDraft("w", START)).toEqual({
      id: "w",
      started_at: "2026-09-30T08:00:00.000Z",
      blocks: [],
      restUntil: null,
      program: null,
      title: null,
    });
  });

  it("prefills new rows from last time, then from the row above", () => {
    let draft = withBench([
      { reps: 8, load_kg: 60, duration_s: null },
      { reps: 6, load_kg: 65, duration_s: null },
    ]);
    draft = addSet(draft, "b", "s2");
    draft = updateSet(draft, "b", "s2", { reps: "7" });
    draft = addSet(draft, "b", "s3");

    expect(block(draft).sets).toEqual([
      row({ id: "s1", kg: "60", reps: "8" }),
      row({ id: "s2", kg: "65", reps: "7" }),
      row({ id: "s3", kg: "65", reps: "7" }),
    ]);
  });

  it("starts blank without a last time", () => {
    const draft = addBlock(newDraft("w", START), { block: "h", set: "s1" }, HANG, []);

    expect(block(draft)).toEqual({
      key: "h",
      exercise: HANG,
      previous: [],
      sets: [row({ id: "s1" })],
      slot_id: null,
      plan: null,
    });
  });

  it("prefills a timed row with last time's hold", () => {
    const draft = addBlock(newDraft("w", START), { block: "h", set: "s1" }, HANG, [
      { reps: null, load_kg: null, duration_s: 50 },
    ]);

    expect(block(draft).sets).toEqual([row({ id: "s1", seconds: "50" })]);
  });

  it("changes only the named block and set", () => {
    let draft = addBlock(withBench(), { block: "h", set: "h1" }, HANG, []);
    draft = addSet(draft, "b", "s2");
    draft = updateSet(draft, "b", "s1", { logged: BENCH_8x60 });

    expect(block(draft).sets.map((s) => s.logged)).toEqual([BENCH_8x60, null]);
    expect(block(draft, 1).sets).toEqual([row({ id: "h1" })]);
    expect(loggedSets(draft)).toBe(1);

    draft = removeSet(draft, "b", "s2");
    expect(block(draft).sets.map((s) => s.id)).toEqual(["s1"]);

    draft = removeBlock(draft, "b");
    expect(draft.blocks.map((b) => b.key)).toEqual(["h"]);
    expect(loggedSets(draft)).toBe(0);
  });
});

describe("previousFrom", () => {
  const lift = (
    reps: number | null,
    load_kg: number | null,
    duration_s: number | null = null,
  ): Previous => ({
    reps,
    load_kg,
    duration_s,
  });
  const sessions = [
    { started_at: "2026-09-30T08:00:00+00:00", sets: [lift(1, 1)] },
    { started_at: "2026-09-28T10:00:00+00:00", sets: [lift(8, 60), lift(null, null, 40)] },
    { started_at: "2026-09-21T10:00:00+00:00", sets: [lift(5, 50)] },
  ];

  it("takes the latest session other than this workout", () => {
    expect(previousFrom(sessions, "2026-09-30T08:00:00.000Z")).toEqual([
      { reps: 8, load_kg: 60, duration_s: null },
      { reps: null, load_kg: null, duration_s: 40 },
    ]);
  });

  it("recognises this workout at the server's precision", () => {
    const draft = newDraft("w", new Date("2026-09-30T08:00:00.123Z"));

    expect(previousFrom(sessions, draft.started_at)).toEqual([
      { reps: 8, load_kg: 60, duration_s: null },
      { reps: null, load_kg: null, duration_s: 40 },
    ]);
  });

  it("is empty for a first time", () => {
    expect(previousFrom([], "2026-09-30T08:00:00.000Z")).toEqual([]);
  });
});

describe("restored", () => {
  it("puts a half-edited logged row back to what was sent", () => {
    let draft = addSet(withBench(), "b", "s2");
    draft = updateSet(draft, "b", "s1", { reps: "", logged: BENCH_8x60 });
    draft = updateSet(draft, "b", "s2", { reps: "" });

    expect(block(restored(draft)).sets).toEqual([
      row({ ...BENCH_8x60, id: "s1", logged: BENCH_8x60 }),
      row({ id: "s2", kg: "60", reps: "" }),
    ]);
  });

  it("keeps a completed correction", () => {
    const draft = updateSet(withBench(), "b", "s1", { reps: "9", logged: BENCH_8x60 });

    expect(restored(draft)).toEqual(draft);
  });
});

describe("typedOf", () => {
  it("keeps just what was typed", () => {
    expect(typedOf(row({ ...BENCH_8x60, id: "x", logged: BENCH_8x60 }))).toEqual(BENCH_8x60);
  });
});

const logged = (
  set_number: number,
  client_id: string | null,
  values: Partial<SetEntry>,
): SetEntry => ({
  set_number,
  reps: null,
  load_kg: null,
  duration_s: null,
  rpe: null,
  notes: null,
  client_id,
  ...values,
});

describe("draftFromServer", () => {
  it("rebuilds the blocks with every logged set ticked off", () => {
    const detail: WorkoutDetail = {
      id: 5,
      started_at: "2026-09-30T08:00:00+00:00",
      ended_at: null,
      notes: null,
      client_id: "w",
      exercises: [
        {
          position: 1,
          exercise_id: 7,
          name: "Bench Press",
          measure: "reps",
          carried_kg: 0,
          sets: [logged(1, "a", { reps: 8, load_kg: 60, rpe: 9 }), logged(2, null, { reps: 8 })],
          block_exercise_id: null,
        },
        {
          position: 2,
          exercise_id: 9,
          name: "Dead Hang",
          measure: "seconds",
          carried_kg: 65,
          sets: [logged(1, "b", { duration_s: 45 })],
          block_exercise_id: null,
        },
      ],
      program_day_id: null,
      program_week: null,
    };

    expect(draftFromServer(detail, "w")).toEqual({
      id: "w",
      started_at: "2026-09-30T08:00:00+00:00",
      restUntil: null,
      program: null,
      title: null,
      blocks: [
        {
          key: "server-1",
          exercise: { ...BENCH, equipment: null },
          previous: [],
          sets: [row({ ...BENCH_8x60, rpe: "9", id: "a", logged: { ...BENCH_8x60, rpe: "9" } })],
          slot_id: null,
          plan: null,
        },
        {
          key: "server-2",
          exercise: HANG,
          previous: [],
          sets: [
            row({
              id: "b",
              seconds: "45",
              logged: { kg: "", reps: "", seconds: "45", rpe: "" },
            }),
          ],
          slot_id: null,
          plan: null,
        },
      ],
    });
  });
});

describe("writes", () => {
  const draft = addSet(withBench(), "b", "s2");
  const bench = block(draft);
  const second = bench.sets[1] ?? row();

  it("starts, finishes and discards the workout by its id", () => {
    expect(startWrite(draft)).toEqual({
      method: "PUT",
      path: "/api/workouts/w",
      body: { started_at: "2026-09-30T08:00:00.000Z" },
      label: "Start workout",
    });
    expect(finishWrite(draft, new Date("2026-09-30T09:05:00Z"))).toEqual({
      method: "PUT",
      path: "/api/workouts/w",
      body: { started_at: "2026-09-30T08:00:00.000Z", ended_at: "2026-09-30T09:05:00.000Z" },
      label: "Finish workout",
    });
    expect(discardWrite(draft)).toEqual({
      method: "DELETE",
      path: "/api/workouts/w",
      body: null,
      label: "Discard workout",
    });
  });

  it("names a set by its place even in an edited copy", () => {
    const edited = { ...second, reps: "9" };

    expect(
      setWrite(draft, bench, edited, { reps: 9, load_kg: 60, duration_s: null, rpe: null }).label,
    ).toBe("Log set 2 of Bench Press");
  });

  it("logs and deletes a set by its id, in its workout and exercise", () => {
    expect(
      setWrite(draft, bench, second, { reps: 8, load_kg: 60, duration_s: null, rpe: null }),
    ).toEqual({
      method: "PUT",
      path: "/api/sets/s2",
      body: {
        workout_client_id: "w",
        exercise_id: 7,
        reps: 8,
        load_kg: 60,
        duration_s: null,
        rpe: null,
      },
      label: "Log set 2 of Bench Press",
    });
    expect(deleteSetWrite(bench, second)).toEqual({
      method: "DELETE",
      path: "/api/sets/s2",
      body: null,
      label: "Delete set 2 of Bench Press",
    });
  });
});

describe("program days", () => {
  const ids = (): (() => string) => {
    let next = 0;
    return () => {
      next += 1;
      return `r${String(next)}`;
    };
  };
  const workout = {
    id: "w",
    started_at: "2026-10-01T07:00:00.000Z",
    program_name: "Upper / Lower",
  };

  it("labels blocks, and a superset's exercises", () => {
    expect([
      blockLabel(0, 0, 1),
      blockLabel(1, 0, 2),
      blockLabel(1, 1, 2),
      blockLabel(25, 2, 3),
    ]).toEqual(["A", "B1", "B2", "Z3"]);
  });

  it("builds today's workout with every set prefilled from its target", () => {
    const draft = todayDraft(workout, UPPER, ids());

    expect({ ...draft, blocks: [] }).toEqual({
      id: "w",
      started_at: "2026-10-01T07:00:00.000Z",
      restUntil: null,
      program: { day_id: 11, week: 2 },
      title: "Upper A · Week 2",
      blocks: [],
    });
    expect(
      draft.blocks.map((b) => [b.key, b.slot_id, b.plan?.label, b.plan?.group, b.plan?.last]),
    ).toEqual([
      ["slot-1", 1, "A", 0, true],
      ["slot-2", 2, "B1", 1, false],
      ["slot-3", 3, "B2", 1, true],
    ]);
    expect(block(draft, 0)).toMatchObject({
      exercise: { id: 101, name: "Bench Press", measure: "reps", equipment: "barbell" },
      previous: [{ reps: 12, load_kg: 60, duration_s: null }],
      sets: [
        row({ id: "r1", kg: "62.5", reps: "8" }),
        row({ id: "r2", kg: "62.5", reps: "8" }),
        row({ id: "r3", kg: "62.5", reps: "8" }),
      ],
      plan: { rest_s: 120, rep_min: 8, rep_max: 12, target: UPPER.blocks[0]?.exercises[0]?.target },
    });
    expect(block(draft, 1).sets).toEqual([
      row({ id: "r4", kg: "40", reps: "11" }),
      row({ id: "r5", kg: "40", reps: "10" }),
    ]);
    // Timed, and no load to lift: seconds prefilled, kg left empty.
    expect(block(draft, 2).sets).toEqual([
      row({ id: "r6", seconds: "30" }),
      row({ id: "r7", seconds: "30" }),
    ]);
    expect(block(draft, 2).previous).toEqual([]);
  });

  it("leaves kg empty for a target of no added load", () => {
    const day = structuredClone(UPPER);
    const bench = day.blocks[0]?.exercises[0];
    if (bench === undefined) {
      throw new Error("no bench");
    }
    bench.target = { decision: "repeat", load_kg: 0, reps: [8] };

    expect(block(todayDraft(workout, day, ids())).sets).toEqual([row({ id: "r1", reps: "8" })]);
  });

  it("names the deload week", () => {
    expect(todayDraft(workout, { ...UPPER, deload: true, week: 7 }, ids()).title).toBe(
      "Upper A · Deload week",
    );
  });

  it("picks up the server's sets for the day", () => {
    const detail: WorkoutDetail = {
      id: 5,
      started_at: "2026-10-01T07:00:00+00:00",
      ended_at: null,
      notes: null,
      client_id: "w",
      program_day_id: 11,
      program_week: 2,
      exercises: [
        {
          position: 1,
          exercise_id: 101,
          name: "Bench Press",
          measure: "reps",
          carried_kg: 0,
          sets: [logged(1, "a", { reps: 8, load_kg: 62.5 }), logged(2, null, { reps: 1 })],
          block_exercise_id: 1,
        },
        {
          position: 2,
          exercise_id: 101,
          name: "Bench Press",
          measure: "reps",
          carried_kg: 0,
          sets: [logged(1, "z", { reps: 5 })],
          block_exercise_id: null,
        },
      ],
    };

    const draft = todayDraft(workout, UPPER, ids(), detail);

    const done = { kg: "62.5", reps: "8", seconds: "", rpe: "" };
    expect(block(draft, 0).sets).toEqual([row({ ...done, id: "a", logged: done })]);
    expect(block(draft, 1).sets).toHaveLength(2); // not done yet: prefilled
  });

  it("rests per block, and only after a superset's round", () => {
    const draft = todayDraft(workout, UPPER, ids());

    expect(restAfter(block(draft, 0), 90_000)).toBe(120_000);
    expect(restAfter(block(draft, 1), 90_000)).toBeNull();
    expect(restAfter(block(draft, 2), 90_000)).toBe(60_000);
    expect(restAfter(block(withBench()), 90_000)).toBe(90_000);
  });

  it("keeps a superset together, and everything else apart", () => {
    const today = todayDraft(workout, UPPER, ids());
    const extra = addBlock(today, { block: "x", set: "x1" }, BENCH, []);
    const keys = (groups: { key: string }[][]): string[][] =>
      groups.map((g) => g.map((b) => b.key));

    expect(keys(groupBlocks(extra.blocks))).toEqual([["slot-1"], ["slot-2", "slot-3"], ["x"]]);
    const twoAdHoc = addBlock(withBench(), { block: "c", set: "c1" }, BENCH, []);
    expect(keys(groupBlocks(twoAdHoc.blocks))).toEqual([["b"], ["c"]]);
    expect(groupBlocks([])).toEqual([]);
  });

  it("names its program day and exercises in every write", () => {
    const draft = todayDraft(workout, UPPER, ids());
    const bench = block(draft);
    const first = bench.sets[0] ?? row();

    expect(startWrite(draft).body).toEqual({
      started_at: "2026-10-01T07:00:00.000Z",
      program: { day_id: 11, week: 2 },
    });
    expect(finishWrite(draft, new Date("2026-10-01T08:00:00Z")).body).toEqual({
      started_at: "2026-10-01T07:00:00.000Z",
      ended_at: "2026-10-01T08:00:00.000Z",
      program: { day_id: 11, week: 2 },
    });
    expect(
      setWrite(draft, bench, first, { reps: 8, load_kg: 62.5, duration_s: null, rpe: null }).body,
    ).toEqual({
      workout_client_id: "w",
      exercise_id: 101,
      reps: 8,
      load_kg: 62.5,
      duration_s: null,
      rpe: null,
      block_exercise_id: 1,
    });
  });

  it("keeps a server workout's program day, so finishing it still names it", () => {
    const detail: WorkoutDetail = {
      id: 5,
      started_at: "2026-10-01T07:00:00+00:00",
      ended_at: null,
      notes: null,
      client_id: "w",
      program_day_id: 11,
      program_week: 3,
      exercises: [
        {
          position: 1,
          exercise_id: 101,
          name: "Bench Press",
          measure: "reps",
          carried_kg: 0,
          sets: [logged(1, "a", { reps: 8 })],
          block_exercise_id: 1,
        },
      ],
    };

    const draft = draftFromServer(detail, "w");

    expect(draft.program).toEqual({ day_id: 11, week: 3 });
    expect(block(draft).slot_id).toBe(1);
    expect(draftFromServer({ ...detail, program_week: null }, "w").program).toBeNull();
  });

  it("loads a draft saved before programs", () => {
    const old = {
      id: "w",
      started_at: "2026-10-01T07:00:00.000Z",
      restUntil: null,
      blocks: [{ key: "b", exercise: BENCH, previous: [], sets: [] }],
    };

    const parsed = draftSchema.parse(old);

    expect([
      parsed.program,
      parsed.title,
      parsed.blocks[0]?.slot_id,
      parsed.blocks[0]?.plan,
    ]).toEqual([null, null, null, null]);
  });
});
