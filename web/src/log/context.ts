import { createContext, use, useMemo, useSyncExternalStore } from "react";

import type { Outbox } from "../outbox/outbox";
import { OutboxContext } from "../outbox/Sync";
import type { Draft } from "./draft";
import type { DraftStore } from "./store";

/** Where the workout in progress lives; null where logging is not possible. */
export const DraftContext = createContext<DraftStore | null>(null);

export interface Logging {
  outbox: Outbox;
  drafts: DraftStore;
}

/**
 * The outbox and the draft store, or null when the app was rendered without them.
 * The same object for as long as both are, so it is safe as an effect dependency.
 */
export function useLogging(): Logging | null {
  const outbox = use(OutboxContext);
  const drafts = use(DraftContext);
  return useMemo(
    () => (outbox === null || drafts === null ? null : { outbox, drafts }),
    [outbox, drafts],
  );
}

const NONE = (): (() => void) => () => undefined;
const NOTHING = (): null => null;

/** The workout in progress, re-rendering when it changes. */
export function useDraft(drafts: DraftStore | null): Draft | null {
  return useSyncExternalStore(drafts?.subscribe ?? NONE, drafts?.get ?? NOTHING);
}
