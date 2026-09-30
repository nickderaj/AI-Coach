import { useEffect, useState } from "react";
import { z } from "zod";

const measureSchema = z.enum(["reps", "seconds", "distance"]);

const setSchema = z.object({
  set_number: z.number().int(),
  reps: z.number().int().nullable(),
  load_kg: z.number().nullable(),
  duration_s: z.number().nullable(),
  rpe: z.number().int().nullable(),
  notes: z.string().nullable(),
});

const workoutSummarySchema = z.object({
  id: z.number().int(),
  started_at: z.string(),
  ended_at: z.string().nullable(),
  exercises: z.array(z.string()),
  set_count: z.number().int(),
});

const workoutDetailSchema = z.object({
  id: z.number().int(),
  started_at: z.string(),
  ended_at: z.string().nullable(),
  notes: z.string().nullable(),
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
      started_at: z.string(),
      sets: z.array(setSchema),
    }),
  ),
});

export const workoutListSchema = z.array(workoutSummarySchema);
export const exerciseListSchema = z.array(exerciseSummarySchema);
export { exerciseHistorySchema, workoutDetailSchema };

export type Measure = z.infer<typeof measureSchema>;
export type SetEntry = z.infer<typeof setSchema>;
export type WorkoutSummary = z.infer<typeof workoutSummarySchema>;
export type ExerciseSummary = z.infer<typeof exerciseSummarySchema>;

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
 *
 * @internal Exported for tests; the app only uses it through `useApi`.
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
