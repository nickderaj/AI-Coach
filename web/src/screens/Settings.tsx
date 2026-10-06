import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { profileSchema, useApi } from "../api";
import type { Profile } from "../api";
import { Load } from "../components";
import type { Logging } from "../log/context";
import { useLogging } from "../log/context";
import { parseAmount } from "../log/draft";
import { sendTest, pushState, turnOff, turnOn } from "../push";
import type { PushChange, PushState } from "../push";
import { backgroundRestEnabled, setBackgroundRestEnabled } from "../restAudio";
import { href } from "../router";

const PROFILE = "/api/profile";
/** The server refuses anything outside this. */
const MAX_BODYWEIGHT_KG = 500;

type Saving = "idle" | "saved" | "failed";

function BodyWeight({
  profile,
  logging,
}: {
  profile: Profile;
  logging: Logging | null;
}): ReactElement {
  const [text, setText] = useState(
    profile.bodyweight_kg === null ? "" : String(profile.bodyweight_kg),
  );
  const [saving, setSaving] = useState<Saving>("idle");
  const cleared = text.trim() === "";
  const kg = parseAmount(text);
  const valid = cleared || (kg !== null && kg > 0 && kg <= MAX_BODYWEIGHT_KG);

  const save = async (): Promise<void> => {
    if (logging === null) {
      return;
    }
    try {
      await logging.outbox.send({
        method: "PUT",
        path: PROFILE,
        body: { bodyweight_kg: cleared ? null : kg },
        label: "Save body weight",
      });
      setSaving("saved");
    } catch {
      setSaving("failed");
    }
  };

  return (
    <form
      className="card"
      aria-label="Body weight"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <h2>Body weight</h2>
      <p className="muted">
        Counted in the volume of bodyweight exercises (pull-ups, dips, squats…), with any weight you
        add on top.
      </p>
      <label className="field">
        kg
        <input
          inputMode="decimal"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setSaving("idle");
          }}
        />
      </label>
      <button type="submit" className="primary" disabled={!valid || logging === null}>
        Save
      </button>
      {saving === "saved" ? <p role="status">Saved.</p> : null}
      {saving === "failed" ? (
        <p className="error" role="alert">
          Could not save on this phone. Try again.
        </p>
      ) : null}
    </form>
  );
}

/** Why this phone cannot have notifications. */
function Unavailable({ state }: { state: { kind: "unsupported" | "blocked" } }): ReactElement {
  return state.kind === "unsupported" ? (
    <p className="muted">
      This browser can’t show notifications. On an iPhone, add the app to your Home Screen and open
      it from there.
    </p>
  ) : (
    <p className="muted">
      Notifications are blocked for this app. Allow them in the phone’s Settings, then come back.
    </p>
  );
}

type Note = { tone: "status" | "alert"; text: string } | null;

function TestButton(): ReactElement {
  const [note, setNote] = useState<Note>(null);
  return (
    <>
      <button
        type="button"
        className="button"
        onClick={() => {
          setNote(null);
          void sendTest().then((sent) => {
            setNote(
              sent
                ? {
                    tone: "status",
                    text: "Sent. It should arrive in a moment, and it’s in the Inbox.",
                  }
                : { tone: "alert", text: "Could not reach the server. Try again." },
            );
          });
        }}
      >
        Send a test notification
      </button>
      {note === null ? null : (
        <p className={note.tone === "alert" ? "error" : "muted"} role={note.tone}>
          {note.text}
        </p>
      )}
    </>
  );
}

/** The switch, or why there is none. */
function Switch({
  state,
  busy,
  onChange,
}: {
  state: PushState;
  busy: boolean;
  onChange: (on: boolean) => void;
}): ReactElement {
  if (state.kind !== "on" && state.kind !== "off") {
    return <Unavailable state={state} />;
  }
  return (
    <label className="field inline">
      <input
        type="checkbox"
        role="switch"
        checked={state.kind === "on"}
        disabled={busy}
        onChange={(event) => {
          onChange(event.target.checked);
        }}
      />
      Notify me on this phone
    </label>
  );
}

/** Notifications on this phone: a switch, and a test once they are on. */
function Notifications(): ReactElement {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void pushState().then((found) => {
      if (live) {
        setState(found);
      }
    });
    return (): void => {
      live = false;
    };
  }, []);

  const change = async (to: () => Promise<PushChange>): Promise<void> => {
    setBusy(true);
    setError(null);
    const result = await to();
    setBusy(false);
    if (result.kind === "ok") {
      setState(result.state);
    } else {
      setError(result.message);
    }
  };

  return (
    <section className="card" aria-label="Notifications">
      <h2>Notifications</h2>
      <p className="muted">
        When the coach answers while you’re away, or proposes a program. Everything also lands in
        the Inbox.
      </p>
      {state === null ? (
        <p className="muted">Checking…</p>
      ) : (
        <Switch
          state={state}
          busy={busy}
          onChange={(on) => {
            void change(on ? turnOn : turnOff);
          }}
        />
      )}
      {error === null ? null : (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {state?.kind === "on" ? <TestButton /> : null}
    </section>
  );
}

function BackgroundRestTimer(): ReactElement {
  const [enabled, setEnabled] = useState(() => backgroundRestEnabled(localStorage));
  return (
    <section className="card" aria-label="Background rest timer">
      <h2>Background rest timer</h2>
      <p className="muted">
        Shows rest progress in iPhone system media controls and keeps the spoken countdown running
        after you leave Coach.
      </p>
      <label className="field inline">
        <input
          type="checkbox"
          role="switch"
          checked={enabled}
          onChange={(event) => {
            const on = event.target.checked;
            setBackgroundRestEnabled(localStorage, on);
            setEnabled(on);
          }}
        />
        Show rests outside Coach
      </label>
      <p className="muted">
        iPhone treats this like media playback, so it may pause music from another app while you
        rest.
      </p>
    </section>
  );
}

type Queued = { checked: false } | { checked: true; profile: Profile | null };

/**
 * A profile change still waiting in the outbox, if any. It is newer than the
 * server's, or the cached copy shown offline, so editing must start from it:
 * saving the older value again would replace it in the queue.
 */
function useQueuedProfile(logging: Logging | null): Queued {
  const [queued, setQueued] = useState<Queued>({ checked: false });
  // Depend on the outbox itself: it lives as long as the app.
  const outbox = logging?.outbox;
  useEffect(() => {
    let live = true;
    void (outbox?.queued(PROFILE) ?? Promise.resolve(undefined)).then((write) => {
      const parsed = profileSchema.safeParse(write?.body);
      if (live) {
        setQueued({ checked: true, profile: parsed.success ? parsed.data : null });
      }
    });
    return (): void => {
      live = false;
    };
  }, [outbox]);
  return queued;
}

export function Settings(): ReactElement {
  const state = useApi(PROFILE, profileSchema);
  const logging = useLogging();
  const queued = useQueuedProfile(logging);
  return (
    <>
      <a className="back" href={href({ name: "home" })}>
        ‹ Home
      </a>
      <header className="page-head">
        <h1>Settings</h1>
      </header>
      <Load state={state}>
        {(profile) =>
          queued.checked ? (
            <BodyWeight profile={queued.profile ?? profile} logging={logging} />
          ) : (
            <p className="muted">Loading…</p>
          )
        }
      </Load>
      <BackgroundRestTimer />
      <Notifications />
    </>
  );
}
