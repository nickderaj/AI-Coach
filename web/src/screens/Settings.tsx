import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { profileSchema, useApi } from "../api";
import type { Profile } from "../api";
import { Load } from "../components";
import type { Logging } from "../log/context";
import { useLogging } from "../log/context";
import { parseAmount } from "../log/draft";
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
    </>
  );
}
