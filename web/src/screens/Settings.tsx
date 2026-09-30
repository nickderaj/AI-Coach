import { useState } from "react";
import type { ReactElement } from "react";

import { profileSchema, useApi } from "../api";
import type { Profile } from "../api";
import { Load } from "../components";
import type { Logging } from "../log/context";
import { useLogging } from "../log/context";
import { parseAmount } from "../log/draft";
import { href } from "../router";

/** The server refuses anything outside this. */
const MAX_BODYWEIGHT_KG = 500;

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
  const [saved, setSaved] = useState(false);
  const cleared = text.trim() === "";
  const kg = parseAmount(text);
  const valid = cleared || (kg !== null && kg > 0 && kg <= MAX_BODYWEIGHT_KG);

  return (
    <form
      className="card"
      aria-label="Body weight"
      onSubmit={(event) => {
        event.preventDefault();
        void logging?.outbox.send({
          method: "PUT",
          path: "/api/profile",
          body: { bodyweight_kg: cleared ? null : kg },
          label: "Save body weight",
        });
        setSaved(true);
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
            setSaved(false);
          }}
        />
      </label>
      <button type="submit" className="primary" disabled={!valid || logging === null}>
        Save
      </button>
      {saved ? <p role="status">Saved.</p> : null}
    </form>
  );
}

export function Settings(): ReactElement {
  const state = useApi("/api/profile", profileSchema);
  const logging = useLogging();
  return (
    <>
      <a className="back" href={href({ name: "home" })}>
        ‹ Home
      </a>
      <header className="page-head">
        <h1>Settings</h1>
      </header>
      <Load state={state}>{(profile) => <BodyWeight profile={profile} logging={logging} />}</Load>
    </>
  );
}
