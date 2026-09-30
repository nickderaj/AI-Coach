import { describe, expect, it } from "vitest";

import type { SetEntry, WorkoutDetail } from "../api";
import {
  addBlock,
  addSet,
  deleteSetWrite,
  discardWrite,
  draftFromServer,
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
  done: false,
  ...values,
});

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
    [row({ kg: "60", reps: "8" }), { reps: 8, load_kg: 60, duration_s: null }],
    [row({ reps: "12" }), { reps: 12, load_kg: null, duration_s: null }],
    [row({ kg: "60" }), null],
    [row({ kg: "60", reps: "8.5" }), null],
    [row({ kg: "sixty", reps: "8" }), null],
  ])("reps: %j", (set, values) => {
    expect(valuesOf(set, "reps")).toEqual(values);
  });

  it.each([
    [row({ seconds: "45" }), { reps: null, load_kg: null, duration_s: 45 }],
    [row({ kg: "10", seconds: "30.5" }), { reps: null, load_kg: 10, duration_s: 30.5 }],
    [row({ reps: "8" }), null],
  ])("seconds: %j", (set, values) => {
    expect(valuesOf(set, "seconds")).toEqual(values);
  });
});

describe("editing a draft", () => {
  it("starts empty", () => {
    expect(newDraft("w", START)).toEqual({
      id: "w",
      started_at: "2026-09-30T08:00:00.000Z",
      blocks: [],
      restUntil: null,
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
    draft = updateSet(draft, "b", "s1", { done: true });

    expect(block(draft).sets.map((s) => s.done)).toEqual([true, false]);
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

  it("is empty for a first time", () => {
    expect(previousFrom([], "2026-09-30T08:00:00.000Z")).toEqual([]);
  });
});

describe("draftFromServer", () => {
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
          sets: [logged(1, "a", { reps: 8, load_kg: 60 }), logged(2, null, { reps: 8 })],
        },
        {
          position: 2,
          exercise_id: 9,
          name: "Dead Hang",
          measure: "seconds",
          sets: [logged(1, "b", { duration_s: 45 })],
        },
      ],
    };

    expect(draftFromServer(detail, "w")).toEqual({
      id: "w",
      started_at: "2026-09-30T08:00:00+00:00",
      restUntil: null,
      blocks: [
        {
          key: "server-1",
          exercise: { ...BENCH, equipment: null },
          previous: [],
          sets: [row({ id: "a", kg: "60", reps: "8", done: true })],
        },
        {
          key: "server-2",
          exercise: HANG,
          previous: [],
          sets: [row({ id: "b", seconds: "45", done: true })],
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

  it("logs and deletes a set by its id, in its workout and exercise", () => {
    expect(setWrite(draft, bench, second, { reps: 8, load_kg: 60, duration_s: null })).toEqual({
      method: "PUT",
      path: "/api/sets/s2",
      body: { workout_client_id: "w", exercise_id: 7, reps: 8, load_kg: 60, duration_s: null },
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
