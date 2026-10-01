/**
 * The workout being logged, kept on the phone.
 *
 * The draft is the source of truth while training: it survives the app being
 * closed and works without signal. Every change that matters to the server
 * (start, each logged set, corrections, deletions, finish) is also turned into
 * an idempotent write for the outbox, addressed by ids made here.
 */
import { z } from "zod";

import { measureSchema, targetSchema } from "../api";
import type { Measure, PlannedDay, WorkoutDetail } from "../api";
import type { Write } from "../outbox/store";

const exerciseSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  measure: measureSchema,
  equipment: z.string().nullable(),
});

const previousSchema = z.object({
  reps: z.number().nullable(),
  load_kg: z.number().nullable(),
  duration_s: z.number().nullable(),
});

const typedSchema = z.object({
  kg: z.string(),
  reps: z.string(),
  seconds: z.string(),
  // Optional; drafts saved before RPE could be logged have none.
  rpe: z.string().default(""),
});

/** One row of the set table. Values are kept as typed, and parsed when logged. */
const draftSetSchema = typedSchema.extend({
  id: z.string(),
  /**
   * What was last sent to the outbox for this set, or null if it is not logged.
   * The server has (or will have) exactly these values, whatever is typed now.
   */
  logged: typedSchema.nullable(),
});

/** How a program exercise is shown: its place in the day, its rest and its target. */
const planSchema = z.object({
  /** "A", or "A1", "A2", … in a superset. */
  label: z.string(),
  /** Its block's index in the day: a superset's exercises share one. */
  group: z.number().int(),
  /** The last exercise of its block: a round of a superset ends with it. */
  last: z.boolean(),
  rest_s: z.number().int(),
  rep_min: z.number().int(),
  rep_max: z.number().int(),
  target: targetSchema,
});

// Fields added after drafts were first saved default, so older drafts still load.
const blockSchema = z.object({
  key: z.string(),
  exercise: exerciseSchema,
  /** The sets of the last session of this exercise, for the "Previous" column. */
  previous: z.array(previousSchema),
  sets: z.array(draftSetSchema),
  /** The program exercise these sets are for, sent with each one; null outside a program. */
  slot_id: z.number().int().nullable().default(null),
  plan: planSchema.nullable().default(null),
});

export const draftSchema = z.object({
  id: z.string(),
  started_at: z.string(),
  blocks: z.array(blockSchema),
  /** When the rest timer runs out (epoch ms), if it is running. */
  restUntil: z.number().nullable(),
  /** The program day and week this workout trains, sent with it; null outside a program. */
  program: z.object({ day_id: z.number().int(), week: z.number().int() }).nullable().default(null),
  /** "Upper A · Week 2", for the heading. */
  title: z.string().nullable().default(null),
});

export type Draft = z.infer<typeof draftSchema>;
export type DraftBlock = z.infer<typeof blockSchema>;
export type Plan = z.infer<typeof planSchema>;
export type DraftSet = z.infer<typeof draftSetSchema>;
export type DraftExercise = z.infer<typeof exerciseSchema>;
export type Previous = z.infer<typeof previousSchema>;
export type Typed = z.infer<typeof typedSchema>;

export interface SetValues {
  reps: number | null;
  load_kg: number | null;
  duration_s: number | null;
  rpe: number | null;
}

/**
 * Whole seconds, as the server stores times; compare times with this.
 *
 * @internal Exported for tests.
 */
export function toSecond(iso: string): number {
  return Math.floor(Date.parse(iso) / 1000);
}

export function newDraft(id: string, now: Date): Draft {
  // Whole seconds, as the server keeps it, so this workout's own session is
  // recognisable when its history comes back.
  const started = new Date(Math.floor(now.getTime() / 1000) * 1000);
  return {
    id,
    started_at: started.toISOString(),
    blocks: [],
    restUntil: null,
    program: null,
    title: null,
  };
}

/** Just the typed values of a row. */
export function typedOf(set: Typed): Typed {
  return { kg: set.kg, reps: set.reps, seconds: set.seconds, rpe: set.rpe };
}

/** A number typed on a phone keypad ("22.5" or "22,5"); null if empty or not one. */
export function parseAmount(text: string): number | null {
  const trimmed = text.trim().replace(",", ".");
  if (trimmed === "") {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

/** RPE as typed: null if left empty, undefined unless a whole number from 1 to 10. */
function rpeOf(text: string): number | null | undefined {
  if (text.trim() === "") {
    return null;
  }
  const value = parseAmount(text);
  return value !== null && Number.isInteger(value) && value >= 1 && value <= 10 ? value : undefined;
}

/** What a row would log, or null while it is incomplete or has something unreadable. */
export function valuesOf(set: Typed, measure: Measure): SetValues | null {
  const load_kg = parseAmount(set.kg);
  const rpe = rpeOf(set.rpe);
  if ((load_kg === null && set.kg.trim() !== "") || rpe === undefined) {
    return null;
  }
  if (measure === "seconds") {
    const duration_s = parseAmount(set.seconds);
    return duration_s === null ? null : { reps: null, load_kg, duration_s, rpe };
  }
  const reps = parseAmount(set.reps);
  return reps === null || !Number.isInteger(reps) ? null : { reps, load_kg, duration_s: null, rpe };
}

function text(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/** A new row: last session's matching set if there was one, else a copy of the row above. */
function prefilled(block: DraftBlock, id: string): DraftSet {
  const previous = block.previous[block.sets.length];
  if (previous !== undefined) {
    const { reps, load_kg, duration_s } = previous;
    const typed = { kg: text(load_kg), reps: text(reps), seconds: text(duration_s), rpe: "" };
    return { id, ...typed, logged: null };
  }
  const above = block.sets.at(-1);
  return {
    id,
    kg: above?.kg ?? "",
    reps: above?.reps ?? "",
    seconds: above?.seconds ?? "",
    rpe: "",
    logged: null,
  };
}

export function addBlock(
  draft: Draft,
  ids: { block: string; set: string },
  exercise: DraftExercise,
  previous: Previous[],
): Draft {
  const block: DraftBlock = {
    key: ids.block,
    exercise,
    previous,
    sets: [],
    slot_id: null,
    plan: null,
  };
  return { ...draft, blocks: [...draft.blocks, { ...block, sets: [prefilled(block, ids.set)] }] };
}

export function removeBlock(draft: Draft, key: string): Draft {
  return { ...draft, blocks: draft.blocks.filter((block) => block.key !== key) };
}

function mapBlock(draft: Draft, key: string, change: (block: DraftBlock) => DraftBlock): Draft {
  return {
    ...draft,
    blocks: draft.blocks.map((block) => (block.key === key ? change(block) : block)),
  };
}

export function addSet(draft: Draft, key: string, id: string): Draft {
  return mapBlock(draft, key, (block) => ({
    ...block,
    sets: [...block.sets, prefilled(block, id)],
  }));
}

export function removeSet(draft: Draft, key: string, id: string): Draft {
  return mapBlock(draft, key, (block) => ({
    ...block,
    sets: block.sets.filter((set) => set.id !== id),
  }));
}

export function updateSet(
  draft: Draft,
  key: string,
  id: string,
  change: Partial<Omit<DraftSet, "id">>,
): Draft {
  return mapBlock(draft, key, (block) => ({
    ...block,
    sets: block.sets.map((set) => (set.id === id ? { ...set, ...change } : set)),
  }));
}

export function loggedSets(draft: Draft): number {
  return draft.blocks.reduce(
    (total, block) => total + block.sets.filter((set) => set.logged !== null).length,
    0,
  );
}

/**
 * The sets of the most recent session before this workout, newest session first
 * as the API lists them.
 */
export function previousFrom(
  sessions: { started_at: string; sets: Previous[] }[],
  startedAt: string,
): Previous[] {
  const since = toSecond(startedAt);
  const last = sessions.find((session) => toSecond(session.started_at) !== since);
  return (last?.sets ?? []).map(({ reps, load_kg, duration_s }) => ({ reps, load_kg, duration_s }));
}

function loggedRow(id: string, values: SetValues): DraftSet {
  const shown = {
    kg: text(values.load_kg),
    reps: text(values.reps),
    seconds: text(values.duration_s),
    rpe: text(values.rpe),
  };
  return { id, ...shown, logged: shown };
}

/**
 * The draft as it was last sent: a logged row left half-edited (the app closed
 * mid-correction) shows what the server has again. Run when the app starts.
 */
export function restored(draft: Draft): Draft {
  return {
    ...draft,
    blocks: draft.blocks.map((block) => ({
      ...block,
      sets: block.sets.map((set) =>
        set.logged !== null && valuesOf(set, block.exercise.measure) === null
          ? { ...set, ...set.logged }
          : set,
      ),
    })),
  };
}

/** Pick a workout back up from the server, e.g. after the phone's copy was lost. */
export function draftFromServer(detail: WorkoutDetail, id: string): Draft {
  return {
    id,
    started_at: detail.started_at,
    restUntil: null,
    // Kept, so finishing it still names its program day (the server insists).
    program:
      detail.program_day_id === null || detail.program_week === null
        ? null
        : { day_id: detail.program_day_id, week: detail.program_week },
    title: null,
    blocks: detail.exercises.map((block) => ({
      key: `server-${String(block.position)}`,
      exercise: {
        id: block.exercise_id,
        name: block.name,
        measure: block.measure,
        equipment: null,
      },
      previous: [],
      // Every set logged from the app has a client id; there are no others to show.
      sets: loggedRows(block.sets),
      slot_id: block.block_exercise_id,
      plan: null,
    })),
  };
}

function loggedRows(sets: WorkoutDetail["exercises"][number]["sets"]): DraftSet[] {
  return sets.flatMap((set) => (set.client_id === null ? [] : [loggedRow(set.client_id, set)]));
}

/** A row prefilled from a target: its load, and the set's reps or seconds. */
function targetRow(id: string, measure: Measure, load_kg: number | null, amount: number): DraftSet {
  const goal = String(amount);
  return {
    id,
    // No load at all, or none added to body weight: left empty either way.
    kg: load_kg === null || load_kg === 0 ? "" : String(load_kg),
    reps: measure === "seconds" ? "" : goal,
    seconds: measure === "seconds" ? goal : "",
    rpe: "",
    logged: null,
  };
}

/** "A", "B", … for blocks; a superset's exercises are "A1", "A2", … */
export function blockLabel(block: number, position: number, size: number): string {
  const letter = String.fromCharCode(65 + block);
  return size > 1 ? `${letter}${String(position + 1)}` : letter;
}

/**
 * A workout of today's program day, each set prefilled with its target.
 *
 * `resume` is the server's copy of the workout already training this day, if
 * any: its id and start are kept, and the sets it has logged replace the
 * prefilled rows of their program exercise.
 */
export function todayDraft(
  workout: { id: string; started_at: string; program_name: string },
  day: PlannedDay,
  newId: () => string,
  resume: WorkoutDetail | null = null,
): Draft {
  const week = day.deload ? "Deload week" : `Week ${String(day.week)}`;
  return {
    id: workout.id,
    started_at: workout.started_at,
    restUntil: null,
    program: { day_id: day.id, week: day.week },
    title: `${day.name} · ${week}`,
    blocks: day.blocks.flatMap((block, group) =>
      block.exercises.map((exercise, position) => {
        const done = resume?.exercises.find(
          (b) => b.block_exercise_id === exercise.block_exercise_id,
        );
        const { target, measure } = exercise;
        return {
          key: `slot-${String(exercise.block_exercise_id)}`,
          exercise: {
            id: exercise.exercise_id,
            name: exercise.name,
            measure,
            equipment: exercise.equipment,
          },
          previous: (exercise.last?.sets ?? []).map(({ reps, load_kg, duration_s }) => ({
            reps,
            load_kg,
            duration_s,
          })),
          sets:
            done === undefined
              ? target.reps.map((amount) => targetRow(newId(), measure, target.load_kg, amount))
              : loggedRows(done.sets),
          slot_id: exercise.block_exercise_id,
          plan: {
            label: blockLabel(group, position, block.exercises.length),
            group,
            last: position === block.exercises.length - 1,
            rest_s: block.rest_s,
            rep_min: exercise.rep_min,
            rep_max: exercise.rep_max,
            target,
          },
        };
      }),
    ),
  };
}

/** Rest after ticking a set in ``block``, in ms; null mid-superset (go to the next exercise). */
export function restAfter(block: DraftBlock, standard: number): number | null {
  if (block.plan === null) {
    return standard;
  }
  return block.plan.last ? block.plan.rest_s * 1000 : null;
}

/**
 * The blocks as they are shown: one group per exercise, except that the
 * exercises of a program superset are kept together.
 */
export function groupBlocks(blocks: DraftBlock[]): DraftBlock[][] {
  const groups: DraftBlock[][] = [];
  let previous: number | null = null;
  for (const block of blocks) {
    const group = block.plan?.group ?? null;
    const last = groups.at(-1);
    if (last !== undefined && group !== null && group === previous) {
      last.push(block);
    } else {
      groups.push([block]);
    }
    previous = group;
  }
  return groups;
}

// ---------------------------------------------------------------- writes

/** The program day a workout trains, as its writes name it; nothing outside a program. */
function programOf(draft: Draft): { program?: { day_id: number; week: number } } {
  return draft.program === null ? {} : { program: draft.program };
}

export function startWrite(draft: Draft): Write {
  return {
    method: "PUT",
    path: `/api/workouts/${draft.id}`,
    body: { started_at: draft.started_at, ...programOf(draft) },
    label: "Start workout",
  };
}

export function finishWrite(draft: Draft, now: Date): Write {
  return {
    method: "PUT",
    path: `/api/workouts/${draft.id}`,
    body: { started_at: draft.started_at, ended_at: now.toISOString(), ...programOf(draft) },
    label: "Finish workout",
  };
}

export function discardWrite(draft: Draft): Write {
  return {
    method: "DELETE",
    path: `/api/workouts/${draft.id}`,
    body: null,
    label: "Discard workout",
  };
}

function setLabel(block: DraftBlock, set: DraftSet): string {
  const number = block.sets.findIndex((row) => row.id === set.id) + 1;
  return `set ${String(number)} of ${block.exercise.name}`;
}

export function setWrite(draft: Draft, block: DraftBlock, set: DraftSet, values: SetValues): Write {
  return {
    method: "PUT",
    path: `/api/sets/${set.id}`,
    body: {
      workout_client_id: draft.id,
      exercise_id: block.exercise.id,
      ...values,
      ...(block.slot_id === null ? {} : { block_exercise_id: block.slot_id }),
    },
    label: `Log ${setLabel(block, set)}`,
  };
}

export function deleteSetWrite(block: DraftBlock, set: DraftSet): Write {
  return {
    method: "DELETE",
    path: `/api/sets/${set.id}`,
    body: null,
    label: `Delete ${setLabel(block, set)}`,
  };
}
