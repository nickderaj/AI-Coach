import { useRef, useState } from "react";
import type { ReactElement } from "react";

import type { ExerciseSummary } from "../api";
import { formatSet } from "../format";
import type { Logging } from "../log/context";
import { useDraft, useLogging } from "../log/context";
import { finishWrite, newDraft, setWrite, typedOf, valuesOf } from "../log/draft";
import type { DraftBlock, DraftSet } from "../log/draft";
import { href } from "../router";

const EMPTY: DraftSet = { id: "", kg: "", reps: "", seconds: "", rpe: "", logged: null };

function QuickLogForm({
  exercise,
  logging,
}: {
  exercise: ExerciseSummary;
  logging: Logging;
}): ReactElement {
  const [set, setSet] = useState(EMPTY);
  const [logged, setLogged] = useState<string | null>(null);
  // Set before the first await: a double tap must not log two one-off workouts.
  const saving = useRef(false);
  const [busy, setBusy] = useState(false);
  const timed = exercise.measure === "seconds";
  const values = valuesOf(set, exercise.measure);

  const submit = async (): Promise<void> => {
    if (values === null || saving.current) {
      return;
    }
    saving.current = true;
    setBusy(true);
    const now = new Date();
    const oneOff = newDraft(crypto.randomUUID(), now);
    const row = { ...set, id: crypto.randomUUID(), logged: typedOf(set) };
    const block: DraftBlock = { key: "one-off", exercise, previous: [], sets: [row] };
    await logging.outbox.send({ ...finishWrite(oneOff, now), label: `One-off ${exercise.name}` });
    await logging.outbox.send(setWrite(oneOff, block, row, values));
    setLogged(formatSet(values, exercise.measure));
    setSet(EMPTY);
    saving.current = false;
    setBusy(false);
  };

  return (
    <form
      className="card quick"
      aria-label="Log one set"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h2>Log one set</h2>
      <div className="row-actions">
        <input
          aria-label="kg"
          placeholder="kg"
          inputMode="decimal"
          value={set.kg}
          onChange={(event) => {
            setSet({ ...set, kg: event.target.value });
          }}
        />
        <input
          aria-label={timed ? "seconds" : "reps"}
          placeholder={timed ? "secs" : "reps"}
          inputMode={timed ? "decimal" : "numeric"}
          value={timed ? set.seconds : set.reps}
          onChange={(event) => {
            const typed = event.target.value;
            setSet(timed ? { ...set, seconds: typed } : { ...set, reps: typed });
            setLogged(null);
          }}
        />
        <button type="submit" className="primary" disabled={values === null || busy}>
          Log
        </button>
      </div>
      {logged === null ? null : <p role="status">Logged {logged}.</p>}
    </form>
  );
}

/**
 * Log a single set outside a workout (a few pull-ups at home, say). It is saved
 * as a workout of its own that starts and ends when it is logged.
 */
export function QuickLog({ exercise }: { exercise: ExerciseSummary }): ReactElement | null {
  const logging = useLogging();
  const draft = useDraft(logging?.drafts ?? null);
  if (logging === null) {
    return null;
  }
  if (draft !== null) {
    return (
      <p className="muted">
        A workout is in progress: <a href={href({ name: "log" })}>log sets there</a>.
      </p>
    );
  }
  return <QuickLogForm exercise={exercise} logging={logging} />;
}
