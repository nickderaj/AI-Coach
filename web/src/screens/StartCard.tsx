import type { ReactElement } from "react";

import { currentWorkoutSchema, useApi } from "../api";
import { tone } from "../components";
import { formatDay, formatTime, plural } from "../format";
import type { Logging } from "../log/context";
import { useDraft, useLogging } from "../log/context";
import { draftFromServer, loggedSets, newDraft, startWrite } from "../log/draft";
import type { Draft } from "../log/draft";
import { href, navigate } from "../router";
import { NextDayCard } from "./Today";

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

/**
 * Pick up a workout started on another device, or on this one before its copy
 * was lost. A program day always goes through Today, which checks it afresh
 * and rebuilds its plan (targets, supersets, rests) around the sets it has;
 * any other workout is rebuilt from what the server has.
 */
function PickUp({ logging }: { logging: Logging }): ReactElement | null {
  const current = useApi("/api/workouts/current", currentWorkoutSchema);
  const unfinished = current.status === "ready" ? current.data : null;
  const clientId = unfinished?.client_id ?? null;
  if (unfinished === null || clientId === null) {
    return null;
  }
  const when = `${formatDay(unfinished.started_at)}, ${formatTime(unfinished.started_at)}`;
  if (unfinished.program_day_id !== null) {
    return (
      <a className="link" href={href({ name: "today" })}>
        Resume the unfinished program workout from {when} ›
      </a>
    );
  }
  return (
    <button
      type="button"
      className="link"
      onClick={() => {
        logging.drafts.update((current) => current ?? draftFromServer(unfinished, clientId));
        navigate({ name: "log" });
      }}
    >
      Resume the unfinished workout from {when}
    </button>
  );
}

function Start({ logging }: { logging: Logging }): ReactElement {
  const start = (): void => {
    const fresh = newDraft(crypto.randomUUID(), new Date());
    // Another tab may have started one since this screen was drawn: use that.
    const draft = logging.drafts.update((current) => current ?? fresh);
    if (draft === fresh) {
      void logging.outbox.send(startWrite(fresh));
      navigate({ name: "pick" });
    } else {
      navigate({ name: "log" });
    }
  };

  return (
    <section className="card start tint" style={tone("mauve")}>
      <button type="button" className="primary" onClick={start}>
        Start workout
      </button>
      <PickUp logging={logging} />
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
  return draft === null ? (
    <>
      <NextDayCard />
      <Start logging={logging} />
    </>
  ) : (
    <Resume draft={draft} />
  );
}
