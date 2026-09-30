import { useState } from "react";
import type { ReactElement } from "react";

import {
  createExercise,
  exerciseHistorySchema,
  exerciseListSchema,
  fetchJson,
  useApi,
} from "../api";
import type { CreateResult, ExerciseMatch, ExerciseSummary } from "../api";
import { Avatar, Load, tone } from "../components";
import type { Logging } from "../log/context";
import { useDraft, useLogging } from "../log/context";
import { addBlock, previousFrom } from "../log/draft";
import type { Draft, DraftExercise, Previous } from "../log/draft";
import { href, navigate } from "../router";
import { facts, matches } from "./Exercises";
import { NoWorkout } from "./Log";

/** What exercises can be done with, as the server knows it. */
const EQUIPMENT = [
  "barbell",
  "dumbbell",
  "kettlebell",
  "cable",
  "machine",
  "bodyweight",
  "ez bar",
  "band",
  "other",
] as const;

/** Give up on "last time" rather than keep the owner waiting in a gym with no signal. */
const PREVIOUS_TIMEOUT_MS = 4_000;

/** Most recently done first, then never-done ones by name. */
function recentFirst(exercises: ExerciseSummary[]): ExerciseSummary[] {
  return [...exercises].sort(
    (a, b) =>
      (b.last_done === null ? 0 : Date.parse(b.last_done)) -
        (a.last_done === null ? 0 : Date.parse(a.last_done)) || a.name.localeCompare(b.name),
  );
}

async function previousFor(id: number, startedAt: string): Promise<Previous[]> {
  try {
    const history = await fetchJson(
      `/api/exercises/${String(id)}/history`,
      exerciseHistorySchema,
      AbortSignal.timeout(PREVIOUS_TIMEOUT_MS),
    );
    return previousFrom(history.sessions, startedAt);
  } catch {
    return [];
  }
}

function toDraft(exercise: ExerciseSummary): DraftExercise {
  const { id, name, measure, equipment } = exercise;
  return { id, name, measure, equipment };
}

function Duplicate({
  result,
  name,
  onUse,
  onCreateAnyway,
}: {
  result: Extract<CreateResult, { kind: "duplicate" }>;
  name: string;
  onUse: (match: ExerciseMatch) => void;
  onCreateAnyway: () => void;
}): ReactElement {
  return (
    <div className="notice tint" style={tone("peach")} role="alert">
      <p>
        {result.reason === "exists"
          ? "That exercise is already in your list."
          : "That looks like an exercise you already have."}
      </p>
      <div className="row-actions">
        {result.matches.map((match) => (
          <button
            key={match.id}
            type="button"
            className="chip"
            onClick={() => {
              onUse(match);
            }}
          >
            Use {match.name}
          </button>
        ))}
        {result.reason === "similar" ? (
          <button type="button" className="chip" onClick={onCreateAnyway}>
            No, add “{name}”
          </button>
        ) : null}
      </div>
    </div>
  );
}

function NewExercise({
  exercises,
  initialName,
  onAdd,
}: {
  exercises: ExerciseSummary[];
  initialName: string;
  onAdd: (exercise: DraftExercise) => void;
}): ReactElement {
  const [name, setName] = useState(initialName.trim());
  const [equipment, setEquipment] = useState("");
  const [timed, setTimed] = useState(false);
  const [result, setResult] = useState<CreateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const measure = timed ? "seconds" : "reps";

  const create = async (allowSimilar: boolean): Promise<void> => {
    setBusy(true);
    const outcome = await createExercise({
      name: name.trim(),
      equipment: equipment === "" ? null : equipment,
      measure,
      allow_similar: allowSimilar,
    });
    setBusy(false);
    if (outcome.kind === "created") {
      onAdd(toDraft(outcome.exercise));
    } else {
      setResult(outcome);
    }
  };
  const use = (match: ExerciseMatch): void => {
    const known = exercises.find((exercise) => exercise.id === match.id);
    onAdd(known === undefined ? { ...match, measure } : toDraft(known));
  };

  return (
    <form
      className="card"
      aria-label="New exercise"
      onSubmit={(event) => {
        event.preventDefault();
        void create(false);
      }}
    >
      <h2>New exercise</h2>
      <label className="field">
        Name
        <input
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            setResult(null);
          }}
        />
      </label>
      <label className="field">
        Equipment
        <select
          value={equipment}
          onChange={(event) => {
            setEquipment(event.target.value);
            setResult(null);
          }}
        >
          <option value="">None</option>
          {EQUIPMENT.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </label>
      <label className="field inline">
        <input
          type="checkbox"
          checked={timed}
          onChange={(event) => {
            setTimed(event.target.checked);
          }}
        />
        Timed (a hold, logged in seconds)
      </label>
      {result?.kind === "duplicate" ? (
        <Duplicate
          result={result}
          name={name.trim()}
          onUse={use}
          onCreateAnyway={() => {
            void create(true);
          }}
        />
      ) : null}
      {result?.kind === "error" ? (
        <p className="error" role="alert">
          {result.message}
        </p>
      ) : null}
      <button type="submit" className="primary" disabled={busy || name.trim().length < 2}>
        Add exercise
      </button>
    </form>
  );
}

function Choose({ logging, draft }: { logging: Logging; draft: Draft }): ReactElement {
  const state = useApi("/api/exercises", exerciseListSchema);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [adding, setAdding] = useState(false);

  const add = async (exercise: DraftExercise): Promise<void> => {
    setAdding(true);
    const previous = await previousFor(exercise.id, draft.started_at);
    const ids = { block: crypto.randomUUID(), set: crypto.randomUUID() };
    logging.drafts.set(addBlock(logging.drafts.get() ?? draft, ids, exercise, previous));
    navigate({ name: "log" });
  };

  return (
    <>
      <a className="back" href={href({ name: "log" })}>
        ‹ Workout
      </a>
      <header className="page-head">
        <h1>Add exercise</h1>
      </header>
      <input
        className="search"
        type="search"
        placeholder="Search exercises"
        aria-label="Search exercises"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      <Load state={state}>
        {(exercises) =>
          creating ? (
            <NewExercise
              exercises={exercises}
              initialName={query}
              onAdd={(exercise) => {
                void add(exercise);
              }}
            />
          ) : (
            <>
              <button
                type="button"
                className="chip"
                onClick={() => {
                  setCreating(true);
                }}
              >
                + New exercise
              </button>
              <ul className="list">
                {recentFirst(exercises)
                  .filter((exercise) => matches(exercise, query))
                  .map((exercise) => (
                    <li key={exercise.id}>
                      <button
                        type="button"
                        className="card exercise-row pick"
                        disabled={adding}
                        onClick={() => {
                          void add(toDraft(exercise));
                        }}
                      >
                        <Avatar name={exercise.name} equipment={exercise.equipment} />
                        <span>
                          <strong>{exercise.name}</strong>
                          <span className="muted">{facts(exercise)}</span>
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>
            </>
          )
        }
      </Load>
    </>
  );
}

export function Picker(): ReactElement {
  const logging = useLogging();
  const draft = useDraft(logging?.drafts ?? null);
  return logging === null || draft === null ? (
    <NoWorkout />
  ) : (
    <Choose logging={logging} draft={draft} />
  );
}
