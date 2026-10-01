import { useEffect, useState } from "react";
import { z } from "zod";

export const measureSchema = z.enum(["reps", "seconds", "distance"]);

const setSchema = z.object({
  set_number: z.number().int(),
  reps: z.number().int().nullable(),
  load_kg: z.number().nullable(),
  duration_s: z.number().nullable(),
  rpe: z.number().int().nullable(),
  notes: z.string().nullable(),
  client_id: z.string().nullable(),
});

const workoutSummarySchema = z.object({
  id: z.number().int(),
  started_at: z.string(),
  ended_at: z.string().nullable(),
  exercises: z.array(
    z.object({
      position: z.number().int(),
      name: z.string(),
      measure: measureSchema,
      sets: z.number().int(),
      best: setSchema,
    }),
  ),
  set_count: z.number().int(),
  volume_kg: z.number(),
});

const workoutDetailSchema = z.object({
  id: z.number().int(),
  started_at: z.string(),
  ended_at: z.string().nullable(),
  notes: z.string().nullable(),
  client_id: z.string().nullable(),
  exercises: z.array(
    z.object({
      position: z.number().int(),
      exercise_id: z.number().int(),
      name: z.string(),
      measure: measureSchema,
      /** Body weight moved in each rep, on top of the load (bodyweight exercises). */
      carried_kg: z.number(),
      sets: z.array(setSchema),
      /** The program exercise these sets were for, if any. */
      block_exercise_id: z.number().int().nullable().default(null),
    }),
  ),
  /** The program day and week the workout trains, if any. */
  program_day_id: z.number().int().nullable().default(null),
  program_week: z.number().int().nullable().default(null),
});

const exerciseSummarySchema = z.object({
  id: z.number().int(),
  name: z.string(),
  equipment: z.string().nullable(),
  muscle_groups: z.string().nullable(),
  measure: measureSchema,
  workouts: z.number().int(),
  last_done: z.string().nullable(),
  best_load_kg: z.number().nullable(),
});

const exerciseHistorySchema = z.object({
  exercise: exerciseSummarySchema,
  carried_kg: z.number(),
  sessions: z.array(
    z.object({
      workout_id: z.number().int(),
      position: z.number().int(),
      started_at: z.string(),
      sets: z.array(setSchema),
    }),
  ),
});

export const workoutListSchema = z.array(workoutSummarySchema);
export const exerciseListSchema = z.array(exerciseSummarySchema);
export const currentWorkoutSchema = workoutDetailSchema.nullable();
export const profileSchema = z.object({ bodyweight_kg: z.number().nullable() });
export { exerciseHistorySchema, workoutDetailSchema };

export type Measure = z.infer<typeof measureSchema>;
export type SetEntry = z.infer<typeof setSchema>;
export type WorkoutSummary = z.infer<typeof workoutSummarySchema>;
export type ExerciseSummary = z.infer<typeof exerciseSummarySchema>;
export type WorkoutDetail = z.infer<typeof workoutDetailSchema>;
export type Profile = z.infer<typeof profileSchema>;

/** @internal Exported for tests; the app only sees it through `useApi`. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(status === 404 ? "Not found" : `The server answered ${String(status)}`);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * GET a same-origin JSON endpoint and validate the body against `schema`.
 */
export async function fetchJson<T>(
  path: string,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    signal: signal ?? null,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  const body: unknown = await response.json();
  return schema.parse(body);
}

export type Loadable<T> =
  { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof z.ZodError) {
    return "The server sent data this app does not understand";
  }
  return "Could not reach the server";
}

/** Load `path` once per mount; remount (e.g. via `key`) to load another resource. */
export function useApi<T>(path: string, schema: z.ZodType<T>): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    fetchJson(path, schema, controller.signal).then(
      (data): void => {
        setState({ status: "ready", data });
      },
      (error: unknown): void => {
        if (!controller.signal.aborted) {
          setState({ status: "error", message: describe(error) });
        }
      },
    );
    return (): void => {
      controller.abort();
    };
  }, [path, schema]);
  return state;
}

const matchSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  equipment: z.string().nullable(),
});

const duplicateSchema = z.object({
  detail: z.object({ reason: z.enum(["exists", "similar"]), matches: z.array(matchSchema) }),
});

export type ExerciseMatch = z.infer<typeof matchSchema>;

export interface NewExercise {
  name: string;
  equipment: string;
  measure: "reps" | "seconds";
  /** Create it even though it looks like an existing exercise. */
  allow_similar: boolean;
}

export type CreateResult =
  | { kind: "created"; exercise: ExerciseSummary }
  | { kind: "duplicate"; reason: "exists" | "similar"; matches: ExerciseMatch[] }
  | { kind: "error"; message: string };

/** @internal Exported for tests. */
export const OFFLINE_CREATE =
  "Adding a new exercise needs a connection. Pick an existing one for now.";

/**
 * Add an exercise to the catalogue. Unlike logging this is not queued offline:
 * only the server can tell whether the name duplicates one it already has.
 */
export async function createExercise(exercise: NewExercise): Promise<CreateResult> {
  let response: Response;
  try {
    response = await fetch("/api/exercises", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(exercise),
    });
  } catch {
    return { kind: "error", message: OFFLINE_CREATE };
  }
  const body: unknown = await response.json().catch(() => null);
  const created = exerciseSummarySchema.safeParse(body);
  if (response.ok && created.success) {
    return { kind: "created", exercise: created.data };
  }
  const duplicate = duplicateSchema.safeParse(body);
  if (response.status === 409 && duplicate.success) {
    return { kind: "duplicate", ...duplicate.data.detail };
  }
  return { kind: "error", message: new ApiError(response.status).message };
}

const coachMessageSchema = z.object({
  role: z.enum(["user", "assistant"]),
  text: z.string(),
  at: z.string(),
});

const coachHistorySchema = z.array(coachMessageSchema);

/** The server's reason when the coach cannot answer: "the coach is not set up", say. */
const detailSchema = z.object({ detail: z.string() });

export type CoachMessage = z.infer<typeof coachMessageSchema>;

export type CoachResult<T> = { kind: "ok"; value: T } | { kind: "error"; message: string };

/** @internal Exported for tests. */
export const OFFLINE_COACH = "Talking to the coach needs a connection.";
/** @internal Exported for tests. */
export const BUSY_COACH = "The coach is still answering your last message.";

const COACH_MESSAGES = "/api/coach/messages";

/** "the coach is not set up" → "The coach is not set up." */
function sentence(text: string): string {
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
}

async function coachRequest<T>(init: RequestInit, schema: z.ZodType<T>): Promise<CoachResult<T>> {
  let response: Response;
  try {
    response = await fetch(COACH_MESSAGES, {
      ...init,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
    });
  } catch {
    return { kind: "error", message: OFFLINE_COACH };
  }
  const body: unknown = await response.json().catch(() => null);
  const parsed = schema.safeParse(body);
  if (response.ok && parsed.success) {
    return { kind: "ok", value: parsed.data };
  }
  if (response.status === 409) {
    return { kind: "error", message: BUSY_COACH };
  }
  const detail = detailSchema.safeParse(body);
  if (response.status === 503 && detail.success) {
    return { kind: "error", message: sentence(detail.data.detail) };
  }
  return { kind: "error", message: new ApiError(response.status).message };
}

/** The conversation so far, oldest first. Needs a connection, like every coach call. */
export function coachHistory(signal: AbortSignal): Promise<CoachResult<CoachMessage[]>> {
  return coachRequest({ signal }, coachHistorySchema);
}

/** Say `text` to the coach and wait for its reply, which can take a while. */
export function askCoach(text: string): Promise<CoachResult<CoachMessage>> {
  return coachRequest({ method: "POST", body: JSON.stringify({ text }) }, coachMessageSchema);
}

const programExerciseSchema = z.object({
  /** The program exercise: what a set logged for it names. */
  id: z.number().int(),
  exercise_id: z.number().int(),
  name: z.string(),
  equipment: z.string().nullable(),
  measure: measureSchema,
  sets: z.number().int(),
  /** The range each set aims for: reps, or seconds for a timed exercise. */
  rep_min: z.number().int(),
  rep_max: z.number().int(),
  start_load_kg: z.number().nullable(),
  notes: z.string().nullable(),
});

const programSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  notes: z.string().nullable(),
  training_weeks: z.number().int(),
  status: z.enum(["proposed", "active", "archived"]),
  started_at: z.string().nullable(),
  /** In order: day 1 first, and each day's blocks in order. */
  days: z.array(
    z.object({
      id: z.number().int(),
      name: z.string(),
      blocks: z.array(
        z.object({ rest_s: z.number().int(), exercises: z.array(programExerciseSchema) }),
      ),
    }),
  ),
});

/** A week (from 1; the one after the training weeks is the deload) and a day (from 1). */
const positionSchema = z.object({ week: z.number().int(), day: z.number().int() });

export const programsSchema = z.object({
  active: programSchema.nullable(),
  proposed: programSchema.nullable(),
  /** The active program's next day; null without one, or once its block is done. */
  next: positionSchema.nullable(),
});

export type Program = z.infer<typeof programSchema>;
export type ProgramDay = Program["days"][number];
export type Position = z.infer<typeof positionSchema>;

/** @internal Exported for tests. */
export const OFFLINE_PROGRAM = "Changing your program needs a connection.";

/**
 * Accept or turn down the proposed program shown, by its id: the server refuses
 * (409) if another has replaced it since. Not queued offline: it changes what
 * every later screen shows, so it happens now or not at all.
 */
export async function changeProgram(
  change: { accept: number } | { decline: number },
): Promise<CoachResult<null>> {
  const [id, verb] = "accept" in change ? [change.accept, "accept"] : [change.decline, "decline"];
  const path = `/api/programs/${String(id)}/${verb}`;
  const method = "POST";
  let response: Response;
  try {
    response = await fetch(path, { method, headers: { Accept: "application/json" } });
  } catch {
    return { kind: "error", message: OFFLINE_PROGRAM };
  }
  if (response.ok) {
    return { kind: "ok", value: null };
  }
  const detail = detailSchema.safeParse(await response.json().catch(() => null));
  return {
    kind: "error",
    message: detail.success ? sentence(detail.data.detail) : new ApiError(response.status).message,
  };
}

/** What the next session of an exercise aims for, and why (the app's rules, D5 and D6). */
export const targetSchema = z.object({
  decision: z.enum(["start", "progress", "repeat", "reduce", "deload"]),
  load_kg: z.number().nullable(),
  /** One prefilled amount per set: reps, or seconds for a timed exercise. */
  reps: z.array(z.number().int()),
});

const plannedExerciseSchema = z.object({
  block_exercise_id: z.number().int(),
  exercise_id: z.number().int(),
  name: z.string(),
  equipment: z.string().nullable(),
  measure: measureSchema,
  carried_kg: z.number(),
  sets: z.number().int(),
  rep_min: z.number().int(),
  rep_max: z.number().int(),
  notes: z.string().nullable(),
  target: targetSchema,
  /** The exercise's last session outside today's workout. */
  last: z.object({ started_at: z.string(), sets: z.array(setSchema) }).nullable(),
});

const plannedDaySchema = z.object({
  id: z.number().int(),
  position: z.number().int(),
  name: z.string(),
  week: z.number().int(),
  deload: z.boolean(),
  blocks: z.array(
    z.object({ rest_s: z.number().int(), exercises: z.array(plannedExerciseSchema) }),
  ),
});

/** The active program's next day, planned; null without an active program. */
export const todaySchema = z
  .object({
    program_id: z.number().int(),
    program_name: z.string(),
    training_weeks: z.number().int(),
    days: z.number().int(),
    /** Null once the block is done. */
    day: plannedDaySchema.nullable(),
    /** An unfinished workout already training that day. */
    workout_client_id: z.string().nullable(),
  })
  .nullable();

export type PlannedDay = z.infer<typeof plannedDaySchema>;
export type TodayPlan = NonNullable<z.infer<typeof todaySchema>>;
