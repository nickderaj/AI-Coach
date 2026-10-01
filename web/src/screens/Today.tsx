import { useState } from "react";
import type { ReactElement } from "react";

import { currentWorkoutSchema, fetchJson, todaySchema, useApi } from "../api";
import type { PlannedDay, TodayPlan } from "../api";
import { Load, tone } from "../components";
import { formatDay, formatSet } from "../format";
import type { Logging } from "../log/context";
import { useDraft, useLogging } from "../log/context";
import { blockLabel, newDraft, startWrite, todayDraft } from "../log/draft";
import type { Draft } from "../log/draft";
import { href, navigate } from "../router";
import { targetLine } from "./Log";

/** "Week 3 of 6 · Upper/Lower", or the deload week. */
function weekLine(today: TodayPlan, day: PlannedDay): string {
  const week = day.deload
    ? "Deload week: fewer sets, lighter"
    : `Week ${String(day.week)} of ${String(today.training_weeks)}`;
  return `${week} · ${today.program_name}`;
}

function Exercises({ day }: { day: PlannedDay }): ReactElement {
  return (
    <ol className="list">
      {day.blocks.map((block, group) => {
        const superset = block.exercises.length > 1;
        return (
          <li
            key={block.exercises[0]?.block_exercise_id}
            className={superset ? "card block superset" : "card block"}
          >
            {superset ? <p className="muted block-kind">Superset</p> : null}
            <ul className="lines">
              {block.exercises.map((exercise, position) => {
                const plan = {
                  label: blockLabel(group, position, block.exercises.length),
                  group,
                  last: false,
                  rest_s: block.rest_s,
                  rep_min: exercise.rep_min,
                  rep_max: exercise.rep_max,
                  target: exercise.target,
                };
                return (
                  <li key={exercise.block_exercise_id} className="planned">
                    <span>
                      <span className="block-letter">{plan.label}</span> {exercise.name}
                    </span>
                    <span className="best">{targetLine(plan, exercise.measure)}</span>
                    <span className="muted last">
                      {exercise.last === null
                        ? "Not done before"
                        : `Last ${formatDay(exercise.last.started_at)}: ${exercise.last.sets
                            .map((set) => formatSet(set, exercise.measure))
                            .join(", ")}`}
                    </span>
                  </li>
                );
              })}
            </ul>
            <p className="muted block-rest">Rest {block.rest_s} s</p>
          </li>
        );
      })}
    </ol>
  );
}

/** Start the day, or carry on with the workout already training it. */
function Begin({
  logging,
  draft,
  today,
  day,
}: {
  logging: Logging;
  draft: Draft | null;
  today: TodayPlan;
  day: PlannedDay;
}): ReactElement {
  const [error, setError] = useState<string | null>(null);
  const program_name = today.program_name;

  if (draft !== null) {
    const same = draft.program?.day_id === day.id;
    return (
      <div className="row-actions">
        {same ? null : <p className="muted">Another workout is in progress.</p>}
        <a className="primary" href={href({ name: "log" })}>
          Resume ›
        </a>
      </div>
    );
  }

  const start = (): void => {
    const fresh = todayDraft(
      { ...newDraft(crypto.randomUUID(), new Date()), program_name },
      day,
      () => crypto.randomUUID(),
    );
    const used = logging.drafts.update((current) => current ?? fresh);
    if (used === fresh) {
      void logging.outbox.send(startWrite(fresh));
    }
    navigate({ name: "log" });
  };

  // The server has this day's workout, but this phone has lost its copy.
  const resume = async (id: string): Promise<void> => {
    setError(null);
    try {
      const detail = await fetchJson("/api/workouts/current", currentWorkoutSchema);
      // Finished elsewhere meanwhile: start the day afresh under its id, in whole seconds.
      const started_at = detail?.started_at ?? newDraft(id, new Date()).started_at;
      const rebuilt = todayDraft(
        { id, started_at, program_name },
        day,
        () => crypto.randomUUID(),
        detail,
      );
      logging.drafts.update((current) => current ?? rebuilt);
      navigate({ name: "log" });
    } catch {
      setError("Picking the workout back up needs a connection.");
    }
  };

  const id = today.workout_client_id;
  return (
    <>
      <button
        type="button"
        className="primary"
        onClick={() => {
          if (id === null) {
            start();
          } else {
            void resume(id);
          }
        }}
      >
        {id === null ? "Start this workout" : "Resume this workout"}
      </button>
      {error === null ? null : (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

function Planned({ today, day }: { today: TodayPlan; day: PlannedDay }): ReactElement {
  const logging = useLogging();
  const draft = useDraft(logging?.drafts ?? null);
  return (
    <>
      <header className="page-head today-head">
        <p className="muted">
          Day {day.position} of {today.days}
        </p>
        <h1>{day.name}</h1>
        <p className={day.deload ? "deload" : "muted"}>{weekLine(today, day)}</p>
        {logging === null ? null : (
          <Begin logging={logging} draft={draft} today={today} day={day} />
        )}
      </header>
      <Exercises day={day} />
    </>
  );
}

function Nothing({ text }: { text: string }): ReactElement {
  return (
    <>
      <h1>Today</h1>
      <p className="muted">{text}</p>
      <a className="button" href={href({ name: "program" })}>
        Program ›
      </a>
    </>
  );
}

/** Today: the active program's next day, with every set's target and last time. */
export function Today(): ReactElement {
  const state = useApi("/api/today", todaySchema);
  return (
    <>
      <a className="back" href={href({ name: "home" })}>
        ‹ Home
      </a>
      <Load state={state}>
        {(today) => {
          if (today === null) {
            return <Nothing text="No program yet. Ask the coach for one." />;
          }
          if (today.day === null) {
            return <Nothing text="Block complete. Ask the coach for your next program." />;
          }
          return <Planned today={today} day={today.day} />;
        }}
      </Load>
    </>
  );
}

/** Home's pointer to the next program day, when there is one and nothing is in progress. */
export function NextDayCard(): ReactElement | null {
  const state = useApi("/api/today", todaySchema);
  const day = state.status === "ready" ? state.data?.day : null;
  if (day === null || day === undefined) {
    return null;
  }
  return (
    <a className="card start tint" style={tone("green")} href={href({ name: "today" })}>
      <strong>Next in your program</strong>
      <span>
        {day.name} · {day.deload ? "Deload week" : `Week ${String(day.week)}`}
      </span>
      <span className="go">Open ›</span>
    </a>
  );
}
