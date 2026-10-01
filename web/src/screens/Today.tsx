import { useState } from "react";
import type { ReactElement } from "react";

import {
  currentWorkoutSchema,
  describeFailure,
  fetchJson,
  isOffline,
  todaySchema,
  useApi,
} from "../api";
import type { PlannedDay, TodayPlan } from "../api";
import { Load, tone } from "../components";
import { formatDay, formatSet } from "../format";
import type { Logging } from "../log/context";
import { useDraft, useLogging } from "../log/context";
import { blockLabel, newDraft, startWrite, todayDraft } from "../log/draft";
import { finishedHere } from "../log/finished";
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

type Outcome = "started" | "stale" | { error: string };

/** @internal Exported for tests. */
export const FINISHED_HERE =
  "You finished this day on this phone. The next one shows once you are back online.";
/** @internal Exported for tests. */
export const RESUME_OFFLINE = "Picking the workout back up needs a connection.";

/** Start `day` as a new workout on this phone, prefilled from its targets. */
function startDay(logging: Logging, program_name: string, day: PlannedDay): Outcome {
  const fresh = todayDraft(
    { ...newDraft(crypto.randomUUID(), new Date()), program_name },
    day,
    () => crypto.randomUUID(),
  );
  const used = logging.drafts.update((current) => current ?? fresh);
  if (used === fresh) {
    void logging.outbox.send(startWrite(fresh));
  }
  return "started";
}

/**
 * Start the day shown, if it is still the day to train. The server is asked
 * afresh (never a saved copy); without signal, the saved plan is used unless
 * this phone has already finished that day.
 */
async function start(logging: Logging, today: TodayPlan, day: PlannedDay): Promise<Outcome> {
  let fresh: TodayPlan | null;
  try {
    fresh = await fetchJson("/api/today", todaySchema, undefined, true);
  } catch (error) {
    // Only no signal falls back to the saved plan; a refusal or an odd answer is shown.
    if (!isOffline(error)) {
      return { error: describeFailure(error) };
    }
    if (finishedHere(localStorage, day.id, day.week)) {
      return { error: FINISHED_HERE };
    }
    return startDay(logging, today.program_name, day);
  }
  const due = stillDue(fresh, day);
  return due === null ? "stale" : startDay(logging, today.program_name, due);
}

/** The day in a fresh plan, if it is still `day` and no workout trains it yet. */
function stillDue(fresh: TodayPlan | null, day: PlannedDay): PlannedDay | null {
  const due = fresh?.day;
  if (due?.id !== day.id || due.week !== day.week || fresh?.workout_client_id !== null) {
    return null;
  }
  return due;
}

/**
 * Pick up the server's workout for this day, which this phone lost: only if it
 * is still the one in progress, for this day and week.
 */
async function resume(
  logging: Logging,
  today: TodayPlan,
  day: PlannedDay,
  id: string,
): Promise<Outcome> {
  let detail;
  try {
    detail = await fetchJson("/api/workouts/current", currentWorkoutSchema, undefined, true);
  } catch (error) {
    return { error: isOffline(error) ? RESUME_OFFLINE : describeFailure(error) };
  }
  if (
    detail?.client_id !== id ||
    detail.program_day_id !== day.id ||
    detail.program_week !== day.week
  ) {
    return "stale";
  }
  const { started_at } = detail;
  const rebuilt = todayDraft(
    { id, started_at, program_name: today.program_name },
    day,
    () => crypto.randomUUID(),
    detail,
  );
  logging.drafts.update((current) => current ?? rebuilt);
  return "started";
}

/** Start the day, or carry on with the workout already training it. */
function Begin({
  logging,
  draft,
  today,
  day,
  onStale,
}: {
  logging: Logging;
  draft: Draft | null;
  today: TodayPlan;
  day: PlannedDay;
  onStale: () => void;
}): ReactElement {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  const id = today.workout_client_id;
  const begin = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    const outcome = await (id === null
      ? start(logging, today, day)
      : resume(logging, today, day, id));
    setBusy(false);
    if (outcome === "started") {
      navigate({ name: "log" });
    } else if (outcome === "stale") {
      onStale();
    } else {
      setError(outcome.error);
    }
  };
  return (
    <>
      <button
        type="button"
        className="primary"
        disabled={busy}
        onClick={() => {
          void begin();
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

function Planned({
  today,
  day,
  onStale,
}: {
  today: TodayPlan;
  day: PlannedDay;
  onStale: () => void;
}): ReactElement {
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
          <Begin logging={logging} draft={draft} today={today} day={day} onStale={onStale} />
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

function Plan({ onStale }: { onStale: () => void }): ReactElement {
  const state = useApi("/api/today", todaySchema);
  return (
    <Load state={state}>
      {(today) => {
        if (today === null) {
          return <Nothing text="No program yet. Ask the coach for one." />;
        }
        if (today.day === null) {
          return <Nothing text="Block complete. Ask the coach for your next program." />;
        }
        return <Planned today={today} day={today.day} onStale={onStale} />;
      }}
    </Load>
  );
}

/** Today: the active program's next day, with every set's target and last time. */
export function Today(): ReactElement {
  // Bumped to load the plan again when it turns out to have changed.
  const [version, setVersion] = useState(0);
  return (
    <>
      <a className="back" href={href({ name: "home" })}>
        ‹ Home
      </a>
      {version === 0 ? null : (
        <p className="notice tint" style={tone("peach")} role="status">
          The plan had changed since this screen was loaded. This is the current one.
        </p>
      )}
      <Plan
        key={version}
        onStale={() => {
          setVersion((current) => current + 1);
        }}
      />
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
