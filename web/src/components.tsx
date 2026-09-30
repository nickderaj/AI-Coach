import type { ReactElement, ReactNode } from "react";

import type { Loadable, Measure, SetEntry } from "./api";
import { formatSet } from "./format";

/** Render a loading/error placeholder, or the loaded data through `children`. */
export function Load<T>({
  state,
  children,
}: {
  state: Loadable<T>;
  children: (data: T) => ReactNode;
}): ReactElement {
  if (state.status === "loading") {
    return <p className="muted">Loading…</p>;
  }
  if (state.status === "error") {
    return (
      <p className="error" role="alert">
        {state.message}
      </p>
    );
  }
  return <>{children(state.data)}</>;
}

export function SetChips({ sets, measure }: { sets: SetEntry[]; measure: Measure }): ReactElement {
  return (
    <ul className="chips" aria-label="sets">
      {sets.map((set) => (
        <li key={set.set_number} className="chip" title={set.notes ?? undefined}>
          {formatSet(set, measure)}
          {set.rpe === null ? null : <span className="rpe"> @{set.rpe}</span>}
        </li>
      ))}
    </ul>
  );
}
