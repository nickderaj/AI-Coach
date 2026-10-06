import { useState } from "react";
import type { ReactElement } from "react";

import { Avatar, tone } from "../components";
import { formatClock, formatSet, formatTime, plural } from "../format";
import type { Logging } from "../log/context";
import { useDraft, useLogging } from "../log/context";
import {
  addSet,
  deleteSetWrite,
  discardWrite,
  finishWrite,
  groupBlocks,
  loggedSets,
  removeBlock,
  restAfter,
  removeSet,
  setWrite,
  typedOf,
  updateSet,
  valuesOf,
} from "../log/draft";
import type { Draft, DraftBlock, DraftSet, Plan, Typed } from "../log/draft";
import { markFinished } from "../log/finished";
import { useNow } from "../log/useNow";
import { MAX_REST_MS, shiftRestAudio, startRestAudio, stopRestAudio } from "../restAudio";
import { href, navigate } from "../router";

/** Rest started when a set is ticked off. */
const REST_MS = 90_000;
const REST_STEP_MS = 15_000;
/** How long finishing waits for the outbox, so Home shows the workout it just saved. */
const SETTLE_MS = 2_000;

export function NoWorkout(): ReactElement {
  return (
    <>
      <a className="back" href={href({ name: "home" })}>
        ‹ Home
      </a>
      <p className="muted">No workout in progress. Start one from Home.</p>
    </>
  );
}

interface Actions {
  edit: (block: DraftBlock, set: DraftSet, change: Partial<Typed>) => void;
  settle: (block: DraftBlock, set: DraftSet) => void;
  toggle: (block: DraftBlock, set: DraftSet) => void;
  addSet: (block: DraftBlock) => void;
  removeLastSet: (block: DraftBlock) => void;
  removeBlock: (block: DraftBlock) => void;
}

/**
 * The rule for logged rows: the outbox always has what the row's `logged` says.
 * A valid edit is queued at once (the outbox keeps only the latest per set), so
 * the app being closed mid-correction loses nothing; an edit that leaves the
 * row incomplete is not sent, and the row goes back to what was.
 */
function actionsFor({ outbox, drafts }: Logging, draft: Draft): Actions {
  const change = (update: (current: Draft) => Draft): void => {
    drafts.update((current) => (current === null ? null : update(current)));
  };
  const send = (block: DraftBlock, set: DraftSet): void => {
    const values = valuesOf(set, block.exercise.measure);
    if (values !== null) {
      void outbox.send(setWrite(draft, block, set, values));
    }
  };
  const actions: Actions = {
    edit: (block, set, typing) => {
      const edited = { ...set, ...typing };
      const complete = valuesOf(edited, block.exercise.measure) !== null;
      const logged = set.logged !== null && complete ? typedOf(edited) : set.logged;
      change((d) => updateSet(d, block.key, set.id, { ...typing, logged }));
      if (set.logged !== null) {
        send(block, edited);
      }
    },
    settle: (block, set) => {
      if (set.logged !== null && valuesOf(set, block.exercise.measure) === null) {
        change((d) => updateSet(d, block.key, set.id, { ...set.logged }));
      }
    },
    toggle: (block, set) => {
      if (set.logged !== null) {
        change((d) => updateSet(d, block.key, set.id, { logged: null }));
        void outbox.send(deleteSetWrite(block, set));
      } else if (valuesOf(set, block.exercise.measure) !== null) {
        // A program block rests as long as it says, and a superset only after its round.
        const index = block.sets.findIndex((row) => row.id === set.id);
        const rest = restAfter(draft, block, index, REST_MS);
        if (rest !== null && rest > 0) {
          startRestAudio(rest);
        }
        change((d) => ({
          ...updateSet(d, block.key, set.id, { logged: typedOf(set) }),
          restUntil: rest === null ? d.restUntil : Date.now() + rest,
        }));
        send(block, set);
      }
    },
    addSet: (block) => {
      change((d) => addSet(d, block.key, crypto.randomUUID()));
    },
    removeLastSet: (block) => {
      const last = block.sets.at(-1);
      if (last === undefined) {
        return;
      }
      change((d) => removeSet(d, block.key, last.id));
      if (last.logged !== null) {
        void outbox.send(deleteSetWrite(block, last));
      }
    },
    removeBlock: (block) => {
      change((d) => removeBlock(d, block.key));
    },
  };
  return actions;
}

function SetRow({
  block,
  set,
  number,
  actions,
}: {
  block: DraftBlock;
  set: DraftSet;
  number: number;
  actions: Actions;
}): ReactElement {
  const { measure } = block.exercise;
  const timed = measure === "seconds";
  const previous = block.previous[number - 1];
  const ready = valuesOf(set, measure) !== null;
  const amount = timed ? "seconds" : "reps";
  return (
    <tr className={set.logged === null ? undefined : "done"}>
      <td>
        <span className="set-number tint">{number}</span>
      </td>
      <td className="muted">{previous === undefined ? "–" : formatSet(previous, measure)}</td>
      <td>
        <input
          aria-label={`Set ${String(number)} kg`}
          inputMode="decimal"
          value={set.kg}
          onChange={(event) => {
            actions.edit(block, set, { kg: event.target.value });
          }}
          onBlur={() => {
            actions.settle(block, set);
          }}
        />
      </td>
      <td>
        <input
          aria-label={`Set ${String(number)} ${amount}`}
          inputMode={timed ? "decimal" : "numeric"}
          value={timed ? set.seconds : set.reps}
          onChange={(event) => {
            const typed = event.target.value;
            actions.edit(block, set, timed ? { seconds: typed } : { reps: typed });
          }}
          onBlur={() => {
            actions.settle(block, set);
          }}
        />
      </td>
      <td>
        <input
          aria-label={`Set ${String(number)} RPE`}
          inputMode="numeric"
          placeholder="–"
          value={set.rpe}
          onChange={(event) => {
            actions.edit(block, set, { rpe: event.target.value });
          }}
          onBlur={() => {
            actions.settle(block, set);
          }}
        />
      </td>
      <td>
        <button
          type="button"
          className="check"
          aria-label={`Set ${String(number)} done`}
          aria-pressed={set.logged !== null}
          disabled={set.logged === null && !ready}
          onClick={() => {
            actions.toggle(block, set);
          }}
        >
          ✓
        </button>
      </td>
    </tr>
  );
}

const DECISIONS: Record<Plan["target"]["decision"], string> = {
  start: "First time in this program",
  progress: "Up: every set reached the top last time",
  repeat: "Same load: beat last time",
  reduce: "Lighter: work back up",
  deload: "Deload: lighter, fewer sets",
};

/** "Target 3 × 8–12 · 62.5 kg", or with seconds for a timed exercise. */
export function targetLine(plan: Plan, measure: string): string {
  const { target } = plan;
  const range =
    plan.rep_min === plan.rep_max
      ? String(plan.rep_min)
      : `${String(plan.rep_min)}–${String(plan.rep_max)}`;
  const unit = measure === "seconds" ? " s" : "";
  const load =
    target.load_kg === null || target.load_kg === 0 ? "" : ` · ${String(target.load_kg)} kg`;
  return `Target ${String(target.reps.length)} × ${range}${unit}${load}`;
}

function Target({ plan, measure }: { plan: Plan; measure: string }): ReactElement {
  return (
    <p className="target">
      <strong>{targetLine(plan, measure)}</strong>
      <span className={`muted decision ${plan.target.decision}`}>
        {DECISIONS[plan.target.decision]}
      </span>
    </p>
  );
}

function BlockCard({ block, actions }: { block: DraftBlock; actions: Actions }): ReactElement {
  const { exercise, plan } = block;
  const anyDone = block.sets.some((set) => set.logged !== null);
  return (
    <section className="card log-card" aria-label={exercise.name}>
      <header className="exercise-row">
        <Avatar name={exercise.name} equipment={exercise.equipment} />
        <strong>
          {plan === null ? null : <span className="block-letter">{plan.label}</span>}
          {exercise.name}
        </strong>
      </header>
      {plan === null ? null : <Target plan={plan} measure={exercise.measure} />}
      <table className="log-table">
        <thead>
          <tr>
            <th scope="col">Set</th>
            <th scope="col">Previous</th>
            <th scope="col">kg</th>
            <th scope="col">{exercise.measure === "seconds" ? "Secs" : "Reps"}</th>
            <th scope="col">
              <abbr title="Rate of perceived exertion, 1 to 10">RPE</abbr>
            </th>
            <th scope="col">
              <span className="sr-only">Done</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {block.sets.map((set, index) => (
            <SetRow key={set.id} block={block} set={set} number={index + 1} actions={actions} />
          ))}
        </tbody>
      </table>
      <div className="row-actions">
        <button
          type="button"
          className="chip"
          onClick={() => {
            actions.addSet(block);
          }}
        >
          + Add set
        </button>
        {block.sets.length > 1 ? (
          <button
            type="button"
            className="chip"
            onClick={() => {
              actions.removeLastSet(block);
            }}
          >
            − Remove set
          </button>
        ) : null}
        {anyDone ? null : (
          <button
            type="button"
            className="chip"
            onClick={() => {
              actions.removeBlock(block);
            }}
          >
            Remove exercise
          </button>
        )}
      </div>
    </section>
  );
}

/** One exercise, or a superset's exercises together on one rail. */
function Group({ group, actions }: { group: DraftBlock[]; actions: Actions }): ReactElement {
  const cards = group.map((block) => <BlockCard key={block.key} block={block} actions={actions} />);
  const rest = group.at(-1)?.plan?.rest_s;
  if (group.length === 1 || rest === undefined) {
    return <>{cards}</>;
  }
  return (
    <div className="superset-group" role="group" aria-label="Superset">
      <p className="muted superset-note">Superset: one set of each in turn, then rest {rest} s</p>
      {cards}
    </div>
  );
}

function RestTimer({ logging, draft }: { logging: Logging; draft: Draft }): ReactElement | null {
  const now = useNow(500);
  const left = draft.restUntil === null ? 0 : draft.restUntil - now;
  if (left <= 0) {
    return null;
  }
  const shift = (ms: number | null): void => {
    if (ms === null) {
      stopRestAudio();
    } else {
      shiftRestAudio(ms);
    }
    logging.drafts.update((current) =>
      current === null
        ? null
        : {
            ...current,
            restUntil:
              ms === null || current.restUntil === null
                ? null
                : Math.min(current.restUntil + ms, Date.now() + MAX_REST_MS),
          },
    );
  };
  return (
    <div className="rest tint" style={tone("teal")} role="timer" aria-label="Rest">
      <strong>Rest {formatClock(left)}</strong>
      <span className="rest-controls">
        <button
          type="button"
          className="chip"
          onClick={() => {
            shift(-REST_STEP_MS);
          }}
        >
          −15 s
        </button>
        <button
          type="button"
          className="chip"
          onClick={() => {
            shift(REST_STEP_MS);
          }}
        >
          +15 s
        </button>
        <button
          type="button"
          className="chip"
          onClick={() => {
            shift(null);
          }}
        >
          Skip
        </button>
      </span>
    </div>
  );
}

function Elapsed({ since }: { since: string }): ReactElement {
  const now = useNow(1000);
  return <span className="elapsed">{formatClock(now - Date.parse(since))}</span>;
}

type Pending = "empty" | "discard" | null;

function ActiveWorkout({ logging, draft }: { logging: Logging; draft: Draft }): ReactElement {
  const [pending, setPending] = useState<Pending>(null);
  const actions = actionsFor(logging, draft);
  const logged = loggedSets(draft);

  const close = async (write: ReturnType<typeof finishWrite>): Promise<void> => {
    stopRestAudio();
    await logging.outbox.send(write);
    logging.drafts.set(null);
    await Promise.race([
      logging.outbox.idle(),
      new Promise((resolve) => setTimeout(resolve, SETTLE_MS)),
    ]);
    navigate({ name: "home" });
  };

  return (
    <>
      <RestTimer logging={logging} draft={draft} />
      <header className="page-head log-head">
        <span>
          <h1>{draft.title ?? "Workout"}</h1>
          <p className="muted">
            Started {formatTime(draft.started_at)} · <Elapsed since={draft.started_at} /> ·{" "}
            {plural(logged, "set")}
          </p>
        </span>
        <button
          type="button"
          className="primary"
          onClick={() => {
            if (logged === 0) {
              setPending("empty");
            } else {
              if (draft.program !== null) {
                markFinished(localStorage, draft.program.day_id, draft.program.week);
              }
              void close(finishWrite(draft, new Date()));
            }
          }}
        >
          Finish
        </button>
      </header>
      {pending === "empty" ? (
        <p className="notice tint" style={tone("peach")} role="alert">
          Nothing is logged yet. Tick off a set first, or discard the workout.
        </p>
      ) : null}
      {groupBlocks(draft.blocks).map((group) => (
        <Group key={group[0]?.key} group={group} actions={actions} />
      ))}
      <a className="button" href={href({ name: "pick" })}>
        + Add exercise
      </a>
      {pending === "discard" ? (
        <div className="notice tint" style={tone("red")} role="alert">
          <p>Discard this workout and its {plural(logged, "logged set")}?</p>
          <div className="row-actions">
            <button
              type="button"
              className="chip danger"
              onClick={() => {
                void close(discardWrite(draft));
              }}
            >
              Discard
            </button>
            <button
              type="button"
              className="chip"
              onClick={() => {
                setPending(null);
              }}
            >
              Keep
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="link danger"
          onClick={() => {
            setPending("discard");
          }}
        >
          Discard workout
        </button>
      )}
      {/* Room for the rest timer, which floats above the tabs: reserved even when it
          is not showing, so ticking a set moves nothing on screen. */}
      <div className="rest-space" aria-hidden="true" />
    </>
  );
}

export function Log(): ReactElement {
  const logging = useLogging();
  const draft = useDraft(logging?.drafts ?? null);
  return logging === null || draft === null ? (
    <NoWorkout />
  ) : (
    <ActiveWorkout logging={logging} draft={draft} />
  );
}
