import { draftSchema, restored } from "./draft";
import type { Draft } from "./draft";

const KEY = "trainer.workout";

/**
 * The workout in progress, kept in `localStorage` so iOS closing the app loses
 * nothing, and shared by every tab of the app on this phone.
 */
export interface DraftStore {
  get: () => Draft | null;
  /**
   * Change the draft as it is now, re-read from storage so that a change made
   * by another tab is built on rather than overwritten; returns the result.
   */
  update: (change: (current: Draft | null) => Draft | null) => Draft | null;
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

function write(storage: Storage, draft: Draft | null): void {
  if (draft === null) {
    storage.removeItem(KEY);
  } else {
    storage.setItem(KEY, JSON.stringify(draft));
  }
}

export function draftStore(storage: Storage, events: EventTarget): DraftStore {
  const opened = read(storage);
  let current = opened === null ? null : restored(opened);
  if (current !== null) {
    write(storage, current);
  }
  const listeners = new Set<() => void>();
  const notify = (): void => {
    for (const listener of listeners) {
      listener();
    }
  };
  // Another tab changed the workout: show its version.
  const onStorage = (event: Event): void => {
    const { key } = event as StorageEvent;
    if (key === KEY || key === null) {
      current = read(storage);
      notify();
    }
  };

  const update = (change: (draft: Draft | null) => Draft | null): Draft | null => {
    current = change(read(storage));
    write(storage, current);
    notify();
    return current;
  };
  return {
    get: () => current,
    update,
    set(draft): void {
      update(() => draft);
    },
    subscribe(listener): () => void {
      if (listeners.size === 0) {
        events.addEventListener("storage", onStorage);
      }
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) {
          events.removeEventListener("storage", onStorage);
        }
      };
    },
  };
}
