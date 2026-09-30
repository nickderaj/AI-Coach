import { draftSchema } from "./draft";
import type { Draft } from "./draft";

const KEY = "trainer.workout";

/** The workout in progress, kept in `localStorage` so iOS closing the app loses nothing. */
export interface DraftStore {
  get: () => Draft | null;
  set: (draft: Draft | null) => void;
  subscribe: (listener: () => void) => () => void;
}

function read(storage: Storage): Draft | null {
  const raw = storage.getItem(KEY);
  if (raw === null) {
    return null;
  }
  try {
    const parsed = draftSchema.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export function draftStore(storage: Storage): DraftStore {
  let current = read(storage);
  const listeners = new Set<() => void>();
  return {
    get: () => current,
    set(draft): void {
      current = draft;
      if (draft === null) {
        storage.removeItem(KEY);
      } else {
        storage.setItem(KEY, JSON.stringify(draft));
      }
      for (const listener of listeners) {
        listener();
      }
    },
    subscribe(listener): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
