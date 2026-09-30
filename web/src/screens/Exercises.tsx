import { useState } from "react";
import type { ReactElement } from "react";

import { exerciseListSchema, useApi } from "../api";
import type { ExerciseSummary } from "../api";
import { Avatar, Load, equipmentTone, tone } from "../components";
import { formatDay, formatLoad, plural } from "../format";
import { href } from "../router";

function facts(exercise: ExerciseSummary): string {
  const parts = [plural(exercise.workouts, "workout")];
  if (exercise.last_done !== null) {
    parts.push(`last ${formatDay(exercise.last_done)}`);
  }
  if (exercise.best_load_kg !== null) {
    parts.push(`best ${formatLoad(exercise.best_load_kg)}`);
  }
  return parts.join(" · ");
}

function matches(exercise: ExerciseSummary, query: string): boolean {
  const haystack = `${exercise.name} ${exercise.equipment ?? ""} ${exercise.muscle_groups ?? ""}`;
  return haystack.toLowerCase().includes(query.trim().toLowerCase());
}

function equipmentOf(exercises: ExerciseSummary[]): string[] {
  const seen = new Set<string>();
  for (const exercise of exercises) {
    if (exercise.equipment !== null) {
      seen.add(exercise.equipment);
    }
  }
  return [...seen].sort();
}

function Catalogue({ exercises }: { exercises: ExerciseSummary[] }): ReactElement {
  const [query, setQuery] = useState("");
  const [equipment, setEquipment] = useState<string | null>(null);
  const shown = exercises.filter(
    (exercise) =>
      matches(exercise, query) && (equipment === null || exercise.equipment === equipment),
  );
  return (
    <>
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
      <div className="chips" role="group" aria-label="Equipment">
        {equipmentOf(exercises).map((item) => (
          <button
            key={item}
            type="button"
            className="chip"
            style={tone(equipmentTone(item))}
            aria-pressed={equipment === item}
            onClick={() => {
              setEquipment(equipment === item ? null : item);
            }}
          >
            {item}
          </button>
        ))}
      </div>
      <ul className="list">
        {shown.map((exercise) => (
          <li key={exercise.id}>
            <a className="card exercise-row" href={href({ name: "exercise", id: exercise.id })}>
              <Avatar name={exercise.name} equipment={exercise.equipment} />
              <span>
                <strong>{exercise.name}</strong>
                <span className="muted">{facts(exercise)}</span>
              </span>
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}

export function Exercises(): ReactElement {
  const state = useApi("/api/exercises", exerciseListSchema);
  return (
    <>
      <header className="page-head">
        <h1>Exercises</h1>
      </header>
      <Load state={state}>{(exercises) => <Catalogue exercises={exercises} />}</Load>
    </>
  );
}
