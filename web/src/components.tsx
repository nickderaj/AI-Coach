import type { CSSProperties, ReactElement, ReactNode } from "react";

import type { Loadable, Measure, SetEntry, WorkoutSummary } from "./api";
import { formatDay, formatMinutes, formatSet, formatTime, formatVolume, partOfDay } from "./format";
import { href } from "./router";
import { durationMinutes } from "./stats";

/** Render a loading/error placeholder, or the loaded data through `children`. */
export function Load<T>({
  state,
  children,
}: {
  state: Loadable<T>;
  children: (data: T) => ReactNode;
}): ReactElement {
  if (state.status === "loading") {
    return <p className="muted">Loading…</p>;
  }
  if (state.status === "error") {
    return (
      <p className="error" role="alert">
        {state.message}
      </p>
    );
  }
  return <>{children(state.data)}</>;
}

const EQUIPMENT_TONES: Record<string, string> = {
  barbell: "blue",
  dumbbell: "mauve",
  kettlebell: "peach",
  cable: "teal",
  machine: "sapphire",
  bodyweight: "green",
  "ez bar": "lavender",
  band: "pink",
};

/** The Catppuccin accent an exercise is drawn in, from its equipment. */
export function equipmentTone(equipment: string | null): string {
  return EQUIPMENT_TONES[equipment ?? ""] ?? "overlay1";
}

/** Inline style that sets `--tone` for `.tint`, charts and chips. */
export function tone(name: string): CSSProperties {
  return { "--tone": `var(--${name})` } as CSSProperties;
}

function Pill({ color, children }: { color: string; children: ReactNode }): ReactElement {
  return (
    <li className="pill tint" style={tone(color)}>
      {children}
    </li>
  );
}

export function StatTile({
  color,
  value,
  label,
}: {
  color: string;
  value: string;
  label: string;
}): ReactElement {
  return (
    <div className="tile tint" style={tone(color)}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

export function Avatar({
  name,
  equipment,
}: {
  name: string;
  equipment: string | null;
}): ReactElement {
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join("");
  return (
    <span className="avatar tint" style={tone(equipmentTone(equipment))} aria-hidden="true">
      {initials}
    </span>
  );
}

/** Pills for a workout's duration, volume and set count. */
export function WorkoutMeta({
  workout,
}: {
  workout: { started_at: string; ended_at: string | null; volume_kg: number; set_count: number };
}): ReactElement {
  const minutes = durationMinutes(workout);
  return (
    <ul className="meta">
      {minutes === null ? null : <Pill color="sky">⏱ {formatMinutes(minutes)}</Pill>}
      <Pill color="green">🏋 {formatVolume(workout.volume_kg)}</Pill>
      <Pill color="peach">
        {String(workout.set_count)} {workout.set_count === 1 ? "set" : "sets"}
      </Pill>
    </ul>
  );
}

export function WorkoutCard({ workout }: { workout: WorkoutSummary }): ReactElement {
  return (
    <li>
      <a className="card" href={href({ name: "workout", id: workout.id })}>
        <span className="workout-title">
          <strong>{partOfDay(workout.started_at)} workout</strong>
          <span className="muted">
            {formatDay(workout.started_at)} · {formatTime(workout.started_at)}
          </span>
        </span>
        <WorkoutMeta workout={workout} />
        <ul className="lines">
          {workout.exercises.map((line) => (
            <li key={line.position}>
              <span>
                {String(line.sets)} × {line.name}
              </span>
              <span className="best">{formatSet(line.best, line.measure)}</span>
            </li>
          ))}
        </ul>
      </a>
    </li>
  );
}

export function SetTable({ sets, measure }: { sets: SetEntry[]; measure: Measure }): ReactElement {
  const timed = measure === "seconds";
  // A column of dashes says nothing: show RPE only where some set has one.
  const rated = sets.some((set) => set.rpe !== null);
  return (
    <table className="set-table">
      <thead>
        <tr>
          <th scope="col">Set</th>
          <th scope="col">{timed ? "Time" : "Reps × kg"}</th>
          {rated ? <th scope="col">RPE</th> : null}
        </tr>
      </thead>
      <tbody>
        {sets.map((set) => (
          <tr key={set.set_number} title={set.notes ?? undefined}>
            <td>
              <span className="set-number tint">{set.set_number}</span>
            </td>
            <td>{formatSet(set, measure)}</td>
            {rated ? <td className="muted">{set.rpe ?? "–"}</td> : null}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
