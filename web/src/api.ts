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
      sets: z.array(setSchema),
    }),
  ),
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
export { exerciseHistorySchema, workoutDetailSchema };

export type Measure = z.infer<typeof measureSchema>;
export type SetEntry = z.infer<typeof setSchema>;
export type WorkoutSummary = z.infer<typeof workoutSummarySchema>;
export type ExerciseSummary = z.infer<typeof exerciseSummarySchema>;
export type WorkoutDetail = z.infer<typeof workoutDetailSchema>;

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
  equipment: string | null;
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
