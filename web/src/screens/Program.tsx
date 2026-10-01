import { useState } from "react";
import type { ReactElement } from "react";

import { askCoach, changeProgram, programsSchema, useApi } from "../api";
import type { CoachMessage, Position, Program as ProgramData, ProgramDay } from "../api";
import { Load, tone } from "../components";
import { formatDay } from "../format";

/**
 * "A", "B", … for blocks; a superset's exercises are "A1", "A2", …
 *
 * @internal Exported for tests.
 */
export function blockLetter(index: number): string {
  return String.fromCharCode(65 + index);
}

/**
 * "3 × 8–12", or "2 × 30–45 s" for a timed exercise; one number when the range is one.
 *
 * @internal Exported for tests.
 */
export function formatPrescription(exercise: {
  sets: number;
  rep_min: number;
  rep_max: number;
  measure: string;
}): string {
  const range =
    exercise.rep_min === exercise.rep_max
      ? String(exercise.rep_min)
      : `${String(exercise.rep_min)}–${String(exercise.rep_max)}`;
  const unit = exercise.measure === "seconds" ? " s" : "";
  return `${String(exercise.sets)} × ${range}${unit}`;
}

function Day({
  day,
  number,
  next,
  starting,
}: {
  day: ProgramDay;
  number: number;
  next: boolean;
  starting: boolean;
}): ReactElement {
  return (
    <li className="card program-day" aria-current={next ? "step" : undefined}>
      <h3>
        <span className="muted">Day {number}</span> {day.name}
        {next ? (
          <span className="pill tint" style={tone("green")}>
            Next
          </span>
        ) : null}
      </h3>
      <ol className="blocks">
        {day.blocks.map((block, index) => {
          const letter = blockLetter(index);
          const superset = block.exercises.length > 1;
          return (
            <li key={letter} className={superset ? "block superset" : "block"}>
              {superset ? <p className="muted block-kind">Superset</p> : null}
              <ul className="lines">
                {block.exercises.map((exercise, position) => (
                  <li key={exercise.id}>
                    <span>
                      <span className="block-letter">
                        {superset ? `${letter}${String(position + 1)}` : letter}
                      </span>{" "}
                      {exercise.name}
                    </span>
                    <span className="best">
                      {formatPrescription(exercise)}
                      {starting && exercise.start_load_kg !== null
                        ? ` · ${String(exercise.start_load_kg)} kg`
                        : null}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="muted block-rest">Rest {block.rest_s} s</p>
            </li>
          );
        })}
      </ol>
    </li>
  );
}

function Days({
  program,
  next,
  starting,
}: {
  program: ProgramData;
  next: Position | null;
  starting: boolean;
}): ReactElement {
  return (
    <ol className="list program-days">
      {program.days.map((day, index) => (
        <Day
          key={day.id}
          day={day}
          number={index + 1}
          next={next?.day === index + 1}
          starting={starting}
        />
      ))}
    </ol>
  );
}

function Weeks({ weeks, current }: { weeks: number; current: number | null }): ReactElement {
  const all = Array.from({ length: weeks + 1 }, (_, index) => index + 1);
  return (
    <ol className="weeks" aria-label="Weeks">
      {all.map((week) => {
        const deload = week > weeks;
        const done = current === null || week < current;
        return (
          <li
            key={week}
            className={done ? "done" : undefined}
            aria-current={week === current ? "step" : undefined}
            title={deload ? "Deload week" : `Week ${String(week)}`}
          >
            {deload ? "D" : week}
          </li>
        );
      })}
    </ol>
  );
}

function where(program: ProgramData, next: Position | null): string {
  if (next === null) {
    return "Block complete. Ask the coach for your next program.";
  }
  const day = program.days[next.day - 1]?.name ?? "";
  if (next.week > program.training_weeks) {
    return `Deload week: the same days, fewer sets and lighter. Next: ${day}.`;
  }
  return `Week ${String(next.week)} of ${String(program.training_weeks)}. Next: ${day}.`;
}

function Active({ program, next }: { program: ProgramData; next: Position | null }): ReactElement {
  return (
    <section aria-label="Current program">
      <div className="card program-head">
        <h2>{program.name}</h2>
        {program.started_at === null ? null : (
          <p className="muted">Started {formatDay(program.started_at)}</p>
        )}
        <Weeks weeks={program.training_weeks} current={next?.week ?? null} />
        <p className={next !== null && next.week > program.training_weeks ? "deload" : undefined}>
          {where(program, next)}
        </p>
        {program.notes === null ? null : <p className="notes">{program.notes}</p>}
      </div>
      <Days program={program} next={next} starting={false} />
    </section>
  );
}

type Asking = "idle" | "accept" | "decline";

function Proposal({
  program,
  replaces,
  onChanged,
}: {
  program: ProgramData;
  replaces: string | null;
  onChanged: () => void;
}): ReactElement {
  const [asking, setAsking] = useState<Asking>("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = async (what: { accept: number } | "decline"): Promise<void> => {
    setBusy(true);
    setError(null);
    const result = await changeProgram(what);
    setBusy(false);
    if (result.kind === "ok") {
      onChanged();
      return;
    }
    setAsking("idle");
    setError(result.message);
  };

  const accept = (): void => {
    void change({ accept: program.id });
  };

  return (
    <section className="card proposal tint" style={tone("peach")} aria-label="Proposed program">
      <p className="eyebrow">Proposed by your coach</p>
      <h2>{program.name}</h2>
      {program.notes === null ? null : <p className="notes">{program.notes}</p>}
      <p className="muted">
        {String(program.training_weeks)} training weeks, then a deload week. Loads after the first
        session follow your log.
      </p>
      <Days program={program} next={null} starting={true} />
      {asking === "accept" ? (
        <div className="notice tint" style={tone("red")} role="group" aria-label="Replace">
          <p>
            Start “{program.name}”? It replaces “{replaces}”.
          </p>
          <div className="row-actions">
            <button type="button" className="primary" disabled={busy} onClick={accept}>
              Yes, start it
            </button>
            <button
              type="button"
              className="link"
              onClick={() => {
                setAsking("idle");
              }}
            >
              Keep my program
            </button>
          </div>
        </div>
      ) : null}
      {asking === "decline" ? (
        <div className="notice tint" style={tone("red")} role="group" aria-label="Turn down">
          <p>Turn this proposal down? The coach can propose another.</p>
          <div className="row-actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => {
                void change("decline");
              }}
            >
              Yes, turn it down
            </button>
            <button
              type="button"
              className="link"
              onClick={() => {
                setAsking("idle");
              }}
            >
              Keep it
            </button>
          </div>
        </div>
      ) : null}
      {asking === "idle" ? (
        <div className="row-actions">
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() => {
              if (replaces === null) {
                accept();
              } else {
                setAsking("accept");
              }
            }}
          >
            Start this program
          </button>
          <button
            type="button"
            className="link danger"
            onClick={() => {
              setAsking("decline");
            }}
          >
            Turn down
          </button>
        </div>
      ) : null}
      {error === null ? null : (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/**
 * What a request typed here is sent to the coach as.
 *
 * @internal Exported for tests.
 */
export function programRequest(text: string, hasProgram: boolean): string {
  return hasProgram ? `Change my program: ${text}` : `Plan a program for me: ${text}`;
}

interface ProgramRequest {
  draft: string;
  setDraft: (draft: string) => void;
  waiting: boolean;
  reply: CoachMessage | null;
  error: string | null;
  ask: (hasProgram: boolean) => void;
}

/** Asking the coach for a program; kept by the screen, so a reload keeps the reply. */
function useProgramRequest(onAnswered: () => void): ProgramRequest {
  const [draft, setDraft] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [reply, setReply] = useState<CoachMessage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ask = async (hasProgram: boolean): Promise<void> => {
    const text = draft.trim();
    if (text === "" || waiting) {
      return;
    }
    setWaiting(true);
    setError(null);
    setReply(null);
    const result = await askCoach(programRequest(text, hasProgram));
    setWaiting(false);
    if (result.kind === "ok") {
      setDraft("");
      setReply(result.value);
      onAnswered();
      return;
    }
    setError(result.message);
  };

  return {
    draft,
    setDraft,
    waiting,
    reply,
    error,
    ask: (hasProgram): void => {
      void ask(hasProgram);
    },
  };
}

function AskCoach({
  request,
  hasProgram,
}: {
  request: ProgramRequest;
  hasProgram: boolean;
}): ReactElement {
  const { draft, waiting, reply, error } = request;
  return (
    <section className="card" aria-label="Ask the coach">
      <h2>{hasProgram ? "Change it with the coach" : "Plan one with the coach"}</h2>
      <form
        className="composer inline"
        onSubmit={(event) => {
          event.preventDefault();
          request.ask(hasProgram);
        }}
      >
        <label className="sr-only" htmlFor="program-request">
          What you want
        </label>
        <textarea
          id="program-request"
          rows={2}
          maxLength={3900}
          placeholder={
            hasProgram ? "e.g. swap squats for leg press" : "e.g. 4 days, upper/lower, an hour each"
          }
          value={draft}
          onChange={(event) => {
            request.setDraft(event.target.value);
          }}
        />
        <button type="submit" className="primary" disabled={waiting || draft.trim() === ""}>
          Ask
        </button>
      </form>
      {waiting ? (
        <p className="muted" role="status">
          The coach is working on it…
        </p>
      ) : null}
      {reply === null ? null : <p className="bubble assistant reply">{reply.text}</p>}
      {error === null ? null : (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function Programs({
  active,
  proposed,
  next,
  onChanged,
}: {
  active: ProgramData | null;
  proposed: ProgramData | null;
  next: Position | null;
  onChanged: () => void;
}): ReactElement {
  return (
    <>
      {proposed === null ? null : (
        <Proposal program={proposed} replaces={active?.name ?? null} onChanged={onChanged} />
      )}
      {active === null ? (
        <p className="muted">No program yet.</p>
      ) : (
        <Active program={active} next={next} />
      )}
    </>
  );
}

function Loaded({
  request,
  onChanged,
}: {
  request: ProgramRequest;
  onChanged: () => void;
}): ReactElement {
  const state = useApi("/api/programs", programsSchema);
  const hasProgram =
    state.status === "ready" && (state.data.active !== null || state.data.proposed !== null);
  return (
    <>
      <Load state={state}>
        {(programs) => (
          <Programs
            active={programs.active}
            proposed={programs.proposed}
            next={programs.next}
            onChanged={onChanged}
          />
        )}
      </Load>
      <AskCoach request={request} hasProgram={hasProgram} />
    </>
  );
}

/** The Program tab: the block being trained, a proposal to accept, and the coach to ask. */
export function Program(): ReactElement {
  // Bumped to load the programs again after a change.
  const [version, setVersion] = useState(0);
  const reload = (): void => {
    setVersion((current) => current + 1);
  };
  const request = useProgramRequest(reload);
  return (
    <>
      <header className="page-head">
        <h1>Program</h1>
        <p className="muted">Six training weeks, then a deload week.</p>
      </header>
      <Loaded key={version} request={request} onChanged={reload} />
    </>
  );
}
