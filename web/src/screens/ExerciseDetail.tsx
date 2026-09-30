import { useState } from "react";
import type { ReactElement } from "react";
import type { z } from "zod";

import { exerciseHistorySchema, useApi } from "../api";
import { LineChart } from "../charts";
import { Avatar, Load, SetTable, StatTile, equipmentTone, tone } from "../components";
import { formatDate, formatLoad, formatShortDate, formatVolume, plural } from "../format";
import { href } from "../router";
import { chronological, personalRecords, sessionStats } from "../stats";
import type { SessionStats } from "../stats";

type History = z.infer<typeof exerciseHistorySchema>;

interface Metric {
  key: keyof SessionStats;
  label: string;
  color: string;
  format: (value: number) => string;
}

type Metrics = readonly [Metric, ...Metric[]];

const LIFT_METRICS: Metrics = [
  { key: "heaviest", label: "Heaviest", color: "mauve", format: formatLoad },
  { key: "oneRepMax", label: "Est. 1RM", color: "pink", format: formatLoad },
  { key: "volume", label: "Volume", color: "green", format: formatVolume },
  {
    key: "mostReps",
    label: "Most reps",
    color: "peach",
    format: (value) => `${String(value)} reps`,
  },
];

const TIMED_METRICS: Metrics = [
  { key: "longest", label: "Longest", color: "sky", format: (value) => `${String(value)} s` },
];

function Progress({ history }: { history: History }): ReactElement {
  const metrics = history.exercise.measure === "seconds" ? TIMED_METRICS : LIFT_METRICS;
  const [metric, setMetric] = useState<Metric>(metrics[0]);
  const points = chronological(history.sessions).flatMap((session) => {
    const value = sessionStats(session.sets)[metric.key];
    const key = `${String(session.workout_id)}:${String(session.position)}`;
    return value === null ? [] : [{ key, label: formatShortDate(session.started_at), value }];
  });
  const records = personalRecords(history.sessions.map((session) => session.sets));
  return (
    <>
      <section className="card" style={tone(equipmentTone(history.exercise.equipment))}>
        <div className="chips" role="group" aria-label="Chart">
          {metrics.map((option) => (
            <button
              key={option.key}
              type="button"
              className="chip"
              aria-pressed={option.key === metric.key}
              onClick={() => {
                setMetric(option);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
        <LineChart points={points} title={`${metric.label} per session`} format={metric.format} />
      </section>
      <section>
        <h2>Personal records</h2>
        <div className="records">
          {metrics.map((option) => {
            const value = records[option.key];
            return (
              <StatTile
                key={option.key}
                color={option.color}
                value={value === null ? "–" : option.format(value)}
                label={option.label}
              />
            );
          })}
        </div>
      </section>
    </>
  );
}

export function ExerciseDetail({ id }: { id: number }): ReactElement {
  const state = useApi(`/api/exercises/${String(id)}/history`, exerciseHistorySchema);
  return (
    <>
      <a className="back" href={href({ name: "exercises" })}>
        ‹ Exercises
      </a>
      <Load state={state}>
        {(history) => (
          <>
            <header className="page-head exercise-row">
              <Avatar name={history.exercise.name} equipment={history.exercise.equipment} />
              <span>
                <h1>{history.exercise.name}</h1>
                <p className="muted">
                  {[history.exercise.equipment, plural(history.exercise.workouts, "workout")]
                    .filter((part) => part !== null)
                    .join(" · ")}
                </p>
              </span>
            </header>
            <Progress history={history} />
            <section>
              <h2>History</h2>
              <ol className="list">
                {history.sessions.map((session) => (
                  <li
                    key={`${String(session.workout_id)}:${String(session.position)}`}
                    className="card"
                  >
                    <a className="back" href={href({ name: "workout", id: session.workout_id })}>
                      {formatDate(session.started_at)}
                    </a>
                    <SetTable sets={session.sets} measure={history.exercise.measure} />
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
      </Load>
    </>
  );
}
