import type { ReactElement } from "react";

import { useApi, workoutDetailSchema, workoutListSchema } from "../api";
import { Load, SetTable, WorkoutCard, WorkoutMeta } from "../components";
import { formatDate, formatTime, partOfDay } from "../format";
import { href } from "../router";

export function History(): ReactElement {
  const state = useApi("/api/workouts?limit=500", workoutListSchema);
  return (
    <>
      <header className="page-head">
        <h1>History</h1>
      </header>
      <Load state={state}>
        {(workouts) =>
          workouts.length === 0 ? (
            <p className="muted">No workouts yet.</p>
          ) : (
            <ul className="list">
              {workouts.map((workout) => (
                <WorkoutCard key={workout.id} workout={workout} />
              ))}
            </ul>
          )
        }
      </Load>
    </>
  );
}

export function WorkoutDetail({ id }: { id: number }): ReactElement {
  const state = useApi(`/api/workouts/${String(id)}`, workoutDetailSchema);
  return (
    <>
      <a className="back" href={href({ name: "history" })}>
        ‹ History
      </a>
      <Load state={state}>
        {(workout) => (
          <>
            <header className="page-head">
              <h1>{partOfDay(workout.started_at)} workout</h1>
              <p className="muted">
                {formatDate(workout.started_at)} · {formatTime(workout.started_at)}
              </p>
            </header>
            <WorkoutMeta
              workout={{
                ...workout,
                set_count: workout.exercises.reduce((sum, block) => sum + block.sets.length, 0),
                volume_kg: workout.exercises
                  .flatMap((block) => block.sets)
                  .reduce((sum, set) => sum + (set.reps ?? 0) * (set.load_kg ?? 0), 0),
              }}
            />
            {workout.notes === null ? null : <p className="notes">{workout.notes}</p>}
            <ol className="list">
              {workout.exercises.map((block) => (
                <li key={block.position} className="card">
                  <a
                    className="workout-title"
                    href={href({ name: "exercise", id: block.exercise_id })}
                  >
                    <strong>{block.name}</strong>
                  </a>
                  <SetTable sets={block.sets} measure={block.measure} />
                </li>
              ))}
            </ol>
          </>
        )}
      </Load>
    </>
  );
}
