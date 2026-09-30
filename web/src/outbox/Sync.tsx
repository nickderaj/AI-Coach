import { createContext, use, useSyncExternalStore } from "react";
import type { ReactElement } from "react";

import { tone } from "../components";
import { plural } from "../format";
import type { Outbox } from "./outbox";

/** The app's outbox; null where writes are not possible (tests of read-only screens). */
export const OutboxContext = createContext<Outbox | null>(null);

function SyncStatus({ outbox }: { outbox: Outbox }): ReactElement | null {
  const { pending, rejected, offline } = useSyncExternalStore(outbox.subscribe, outbox.status);
  return (
    <>
      {pending === 0 ? null : (
        <p className="sync tint" style={tone(offline ? "peach" : "sky")} role="status">
          {offline
            ? `Offline · ${plural(pending, "change")} saved on this phone, sending when back online`
            : `Saving ${plural(pending, "change")}…`}
        </p>
      )}
      {rejected.length === 0 ? null : (
        <div className="sync tint" style={tone("red")} role="alert">
          <strong>The server refused {plural(rejected.length, "change")}</strong>
          <ul>
            {rejected.map((write) => (
              <li key={write.id}>
                {write.label}: {write.reason}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="chip"
            onClick={() => {
              void outbox.dismissRejected();
            }}
          >
            Dismiss
          </button>
        </div>
      )}
    </>
  );
}

/** Tells the owner about writes that are not on the server yet, or never will be. */
export function SyncBanner(): ReactElement | null {
  const outbox = use(OutboxContext);
  return outbox === null ? null : <SyncStatus outbox={outbox} />;
}
