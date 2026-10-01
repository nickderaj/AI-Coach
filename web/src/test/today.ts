import type { PlannedDay, TodayPlan } from "../api";

/** A planned exercise as /api/today sends it. */
function planned(
  id: number,
  name: string,
  extra: Partial<PlannedDay["blocks"][number]["exercises"][number]> = {},
): PlannedDay["blocks"][number]["exercises"][number] {
  return {
    block_exercise_id: id,
    exercise_id: id + 100,
    name,
    equipment: "barbell",
    measure: "reps",
    carried_kg: 0,
    sets: 3,
    rep_min: 8,
    rep_max: 12,
    notes: null,
    target: { decision: "progress", load_kg: 62.5, reps: [8, 8, 8] },
    last: null,
    ...extra,
  };
}

/** Upper A: bench alone, then rows and curls as a superset. */
export const UPPER: PlannedDay = {
  id: 11,
  position: 1,
  name: "Upper A",
  week: 2,
  deload: false,
  blocks: [
    {
      rest_s: 120,
      exercises: [
        planned(1, "Bench Press", {
          last: {
            started_at: "2026-09-24T08:00:00+00:00",
            sets: [
              {
                set_number: 1,
                reps: 12,
                load_kg: 60,
                duration_s: null,
                rpe: null,
                notes: null,
                client_id: "x",
              },
            ],
          },
        }),
      ],
    },
    {
      rest_s: 60,
      exercises: [
        planned(2, "Cable Row", {
          equipment: "cable",
          sets: 2,
          target: { decision: "repeat", load_kg: 40, reps: [11, 10] },
        }),
        planned(3, "Dead Hang", {
          equipment: "bodyweight",
          measure: "seconds",
          sets: 2,
          rep_min: 30,
          rep_max: 45,
          target: { decision: "start", load_kg: null, reps: [30, 30] },
        }),
      ],
    },
  ],
};

export const TODAY: TodayPlan = {
  program_id: 1,
  program_name: "Upper / Lower",
  training_weeks: 6,
  days: 4,
  day: UPPER,
  workout_client_id: null,
  left_over: null,
};
