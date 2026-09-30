import { useState } from "react";
import type { ReactElement } from "react";

import {
  exerciseHistorySchema,
  exerciseListSchema,
  useApi,
  workoutDetailSchema,
  workoutListSchema,
} from "./api";
import type { ExerciseSummary, WorkoutSummary } from "./api";
import { Load, SetChips } from "./components";
import { formatDate, formatDay, formatLoad, formatTime, plural } from "./format";
import { href } from "./router";

function WorkoutRow({ workout }: { workout: WorkoutSummary }): ReactElement {
  return (
    <li>
      <a className="card" href={href({ name: "workout", id: workout.id })}>
        <span className="card-title">
          {formatDay(workout.started_at)}{" "}
          <span className="muted">{formatTime(workout.started_at)}</span>
        </span>
        <span className="muted">
          {plural(workout.exercises.length, "exercise")} · {plural(workout.set_count, "set")}
        </span>
        <span className="card-body">{workout.exercises.join(" · ")}</span>
      </a>
    </li>
  );
}

export function WorkoutList(): ReactElement {
  const state = useApi("/api/workouts", workoutListSchema);
  return (
    <section>
      <h1>History</h1>
      <Load state={state}>
        {(workouts) =>
          workouts.length === 0 ? (
            <p className="muted">No workouts yet.</p>
          ) : (
            <ul className="list">
              {workouts.map((workout) => (
                <WorkoutRow key={workout.id} workout={workout} />
              ))}
            </ul>
          )
        }
      </Load>
    </section>
  );
}

export function WorkoutDetail({ id }: { id: number }): ReactElement {
  const state = useApi(`/api/workouts/${String(id)}`, workoutDetailSchema);
  return (
    <section>
      <a className="back" href={href({ name: "workouts" })}>
        ‹ History
      </a>
      <Load state={state}>
        {(workout) => (
          <>
            <h1>
              {formatDate(workout.started_at)}{" "}
              <span className="muted">{formatTime(workout.started_at)}</span>
            </h1>
            {workout.notes === null ? null : <p className="notes">{workout.notes}</p>}
            <ol className="list">
              {workout.exercises.map((block) => (
                <li key={block.position} className="block">
                  <a href={href({ name: "exercise", id: block.exercise_id })}>{block.name}</a>
                  <SetChips sets={block.sets} measure={block.measure} />
                </li>
              ))}
            </ol>
          </>
        )}
      </Load>
    </section>
  );
}

function exerciseFacts(exercise: ExerciseSummary): string {
  const facts = [plural(exercise.workouts, "workout")];
  if (exercise.last_done !== null) {
    facts.push(`last ${formatDay(exercise.last_done)}`);
  }
  if (exercise.best_load_kg !== null) {
    facts.push(`best ${formatLoad(exercise.best_load_kg)}`);
  }
  return facts.join(" · ");
}

function matches(exercise: ExerciseSummary, query: string): boolean {
  const haystack = `${exercise.name} ${exercise.equipment ?? ""} ${exercise.muscle_groups ?? ""}`;
  return haystack.toLowerCase().includes(query.trim().toLowerCase());
}

export function ExerciseList(): ReactElement {
  const state = useApi("/api/exercises", exerciseListSchema);
  const [query, setQuery] = useState("");
  return (
    <section>
      <h1>Exercises</h1>
      <input
        className="search"
        type="search"
        placeholder="Search exercises"
        aria-label="Search exercises"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      <Load state={state}>
        {(exercises) => (
          <ul className="list">
            {exercises
              .filter((exercise) => matches(exercise, query))
              .map((exercise) => (
                <li key={exercise.id}>
                  <a className="card" href={href({ name: "exercise", id: exercise.id })}>
                    <span className="card-title">{exercise.name}</span>
                    <span className="muted">{exerciseFacts(exercise)}</span>
                  </a>
                </li>
              ))}
          </ul>
        )}
      </Load>
    </section>
  );
}

export function ExerciseHistory({ id }: { id: number }): ReactElement {
  const state = useApi(`/api/exercises/${String(id)}/history`, exerciseHistorySchema);
  return (
    <section>
      <a className="back" href={href({ name: "exercises" })}>
        ‹ Exercises
      </a>
      <Load state={state}>
        {({ exercise, sessions }) => (
          <>
            <h1>{exercise.name}</h1>
            <p className="muted">{exerciseFacts(exercise)}</p>
            <ol className="list">
              {sessions.map((session) => (
                <li key={session.workout_id} className="block">
                  <a href={href({ name: "workout", id: session.workout_id })}>
                    {formatDate(session.started_at)}
                  </a>
                  <SetChips sets={session.sets} measure={exercise.measure} />
                </li>
              ))}
            </ol>
          </>
        )}
      </Load>
    </section>
  );
}
