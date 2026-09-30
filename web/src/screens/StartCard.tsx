import type { ReactElement } from "react";

import { currentWorkoutSchema, useApi } from "../api";
import { tone } from "../components";
import { formatDay, formatTime, plural } from "../format";
import type { Logging } from "../log/context";
import { useDraft, useLogging } from "../log/context";
import { draftFromServer, loggedSets, newDraft, startWrite } from "../log/draft";
import type { Draft } from "../log/draft";
import { href, navigate } from "../router";

function Resume({ draft }: { draft: Draft }): ReactElement {
  return (
    <a className="card start tint" style={tone("green")} href={href({ name: "log" })}>
      <strong>Workout in progress</strong>
      <span>
        Started {formatTime(draft.started_at)} · {plural(loggedSets(draft), "set")} logged
      </span>
      <span className="go">Resume ›</span>
    </a>
  );
}

function Start({ logging }: { logging: Logging }): ReactElement {
  // A workout started on another device, or on this one before its copy was lost.
  const current = useApi("/api/workouts/current", currentWorkoutSchema);
  const unfinished = current.status === "ready" ? current.data : null;
  const clientId = unfinished?.client_id ?? null;

  const start = (): void => {
    const draft = newDraft(crypto.randomUUID(), new Date());
    logging.drafts.set(draft);
    void logging.outbox.send(startWrite(draft));
    navigate({ name: "pick" });
  };

  return (
    <section className="card start tint" style={tone("mauve")}>
      <button type="button" className="primary" onClick={start}>
        Start workout
      </button>
      {unfinished === null || clientId === null ? null : (
        <button
          type="button"
          className="link"
          onClick={() => {
            logging.drafts.set(draftFromServer(unfinished, clientId));
            navigate({ name: "log" });
          }}
        >
          Resume the unfinished workout from {formatDay(unfinished.started_at)},{" "}
          {formatTime(unfinished.started_at)}
        </button>
      )}
    </section>
  );
}

/** Start, resume or pick up a workout; hidden where logging is not possible. */
export function StartCard(): ReactElement | null {
  const logging = useLogging();
  const draft = useDraft(logging?.drafts ?? null);
  if (logging === null) {
    return null;
  }
  return draft === null ? <Start logging={logging} /> : <Resume draft={draft} />;
}
