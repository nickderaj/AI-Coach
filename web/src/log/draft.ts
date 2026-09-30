/**
 * The workout being logged, kept on the phone.
 *
 * The draft is the source of truth while training: it survives the app being
 * closed and works without signal. Every change that matters to the server
 * (start, each logged set, corrections, deletions, finish) is also turned into
 * an idempotent write for the outbox, addressed by ids made here.
 */
import { z } from "zod";

import { measureSchema } from "../api";
import type { Measure, WorkoutDetail } from "../api";
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

/** One row of the set table. Values are kept as typed, and parsed when logged. */
const draftSetSchema = z.object({
  id: z.string(),
  kg: z.string(),
  reps: z.string(),
  seconds: z.string(),
  done: z.boolean(),
});

const blockSchema = z.object({
  key: z.string(),
  exercise: exerciseSchema,
  /** The sets of the last session of this exercise, for the "Previous" column. */
  previous: z.array(previousSchema),
  sets: z.array(draftSetSchema),
});

export const draftSchema = z.object({
  id: z.string(),
  started_at: z.string(),
  blocks: z.array(blockSchema),
  /** When the rest timer runs out (epoch ms), if it is running. */
  restUntil: z.number().nullable(),
});

export type Draft = z.infer<typeof draftSchema>;
export type DraftBlock = z.infer<typeof blockSchema>;
export type DraftSet = z.infer<typeof draftSetSchema>;
export type DraftExercise = z.infer<typeof exerciseSchema>;
export type Previous = z.infer<typeof previousSchema>;

export interface SetValues {
  reps: number | null;
  load_kg: number | null;
  duration_s: number | null;
}

export function newDraft(id: string, now: Date): Draft {
  return { id, started_at: now.toISOString(), blocks: [], restUntil: null };
}

/**
 * A number typed on a phone keypad ("22.5" or "22,5"); null if empty or not one.
 *
 * @internal Exported for tests; screens use `valuesOf`.
 */
export function parseAmount(text: string): number | null {
  const trimmed = text.trim().replace(",", ".");
  if (trimmed === "") {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

/** What a row would log, or null while it is incomplete or has something unreadable. */
export function valuesOf(set: DraftSet, measure: Measure): SetValues | null {
  const load_kg = parseAmount(set.kg);
  if (load_kg === null && set.kg.trim() !== "") {
    return null;
  }
  if (measure === "seconds") {
    const duration_s = parseAmount(set.seconds);
    return duration_s === null ? null : { reps: null, load_kg, duration_s };
  }
  const reps = parseAmount(set.reps);
  return reps === null || !Number.isInteger(reps) ? null : { reps, load_kg, duration_s: null };
}

function text(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/** A new row: last session's matching set if there was one, else a copy of the row above. */
function prefilled(block: DraftBlock, id: string): DraftSet {
  const previous = block.previous[block.sets.length];
  if (previous !== undefined) {
    const { reps, load_kg, duration_s } = previous;
    return { id, kg: text(load_kg), reps: text(reps), seconds: text(duration_s), done: false };
  }
  const above = block.sets.at(-1);
  return {
    id,
    kg: above?.kg ?? "",
    reps: above?.reps ?? "",
    seconds: above?.seconds ?? "",
    done: false,
  };
}

export function addBlock(
  draft: Draft,
  ids: { block: string; set: string },
  exercise: DraftExercise,
  previous: Previous[],
): Draft {
  const block: DraftBlock = { key: ids.block, exercise, previous, sets: [] };
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
  return draft.blocks.reduce((total, block) => total + block.sets.filter((s) => s.done).length, 0);
}

/**
 * The sets of the most recent session before this workout, newest session first
 * as the API lists them.
 */
export function previousFrom(
  sessions: { started_at: string; sets: Previous[] }[],
  startedAt: string,
): Previous[] {
  const since = Date.parse(startedAt);
  const last = sessions.find((session) => Date.parse(session.started_at) !== since);
  return (last?.sets ?? []).map(({ reps, load_kg, duration_s }) => ({ reps, load_kg, duration_s }));
}

/** Pick a workout back up from the server, e.g. after the phone's copy was lost. */
export function draftFromServer(detail: WorkoutDetail, id: string): Draft {
  return {
    id,
    started_at: detail.started_at,
    restUntil: null,
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
      sets: block.sets.flatMap((set) =>
        set.client_id === null
          ? []
          : [
              {
                id: set.client_id,
                kg: text(set.load_kg),
                reps: text(set.reps),
                seconds: text(set.duration_s),
                done: true,
              },
            ],
      ),
    })),
  };
}

// ---------------------------------------------------------------- writes

export function startWrite(draft: Draft): Write {
  return {
    method: "PUT",
    path: `/api/workouts/${draft.id}`,
    body: { started_at: draft.started_at },
    label: "Start workout",
  };
}

export function finishWrite(draft: Draft, now: Date): Write {
  return {
    method: "PUT",
    path: `/api/workouts/${draft.id}`,
    body: { started_at: draft.started_at, ended_at: now.toISOString() },
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
  return `set ${String(block.sets.indexOf(set) + 1)} of ${block.exercise.name}`;
}

export function setWrite(draft: Draft, block: DraftBlock, set: DraftSet, values: SetValues): Write {
  return {
    method: "PUT",
    path: `/api/sets/${set.id}`,
    body: { workout_client_id: draft.id, exercise_id: block.exercise.id, ...values },
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
