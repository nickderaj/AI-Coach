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
  loggedSets,
  removeBlock,
  removeSet,
  setWrite,
  typedOf,
  updateSet,
  valuesOf,
} from "../log/draft";
import type { Draft, DraftBlock, DraftSet, Typed } from "../log/draft";
import { useNow } from "../log/useNow";
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
        change((d) => ({
          ...updateSet(d, block.key, set.id, { logged: typedOf(set) }),
          restUntil: Date.now() + REST_MS,
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

function BlockCard({ block, actions }: { block: DraftBlock; actions: Actions }): ReactElement {
  const { exercise } = block;
  const anyDone = block.sets.some((set) => set.logged !== null);
  return (
    <section className="card" aria-label={exercise.name}>
      <header className="exercise-row">
        <Avatar name={exercise.name} equipment={exercise.equipment} />
        <strong>{exercise.name}</strong>
      </header>
      <table className="log-table">
        <thead>
          <tr>
            <th scope="col">Set</th>
            <th scope="col">Previous</th>
            <th scope="col">kg</th>
            <th scope="col">{exercise.measure === "seconds" ? "Secs" : "Reps"}</th>
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

function RestTimer({ logging, draft }: { logging: Logging; draft: Draft }): ReactElement | null {
  const now = useNow(500);
  const left = draft.restUntil === null ? 0 : draft.restUntil - now;
  if (left <= 0) {
    return null;
  }
  const shift = (ms: number | null): void => {
    logging.drafts.update((current) =>
      current === null
        ? null
        : {
            ...current,
            restUntil: ms === null || current.restUntil === null ? null : current.restUntil + ms,
          },
    );
  };
  return (
    <div className="rest tint" style={tone("teal")} role="timer" aria-label="Rest">
      <strong>Rest {formatClock(left)}</strong>
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
          <h1>Workout</h1>
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
      {draft.blocks.map((block) => (
        <BlockCard key={block.key} block={block} actions={actions} />
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
