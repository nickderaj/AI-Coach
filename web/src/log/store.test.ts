import { afterEach, describe, expect, it, vi } from "vitest";

import { newDraft } from "./draft";
import { draftStore } from "./store";

const KEY = "trainer.workout";
const draft = newDraft("w", new Date("2026-09-30T08:00:00Z"));

afterEach(() => {
  localStorage.clear();
});

describe("draftStore", () => {
  it("has nothing when no workout is in progress", () => {
    expect(draftStore(localStorage).get()).toBeNull();
  });

  it("keeps the workout across app launches", () => {
    draftStore(localStorage).set(draft);

    expect(draftStore(localStorage).get()).toEqual(draft);
  });

  it("forgets a finished workout", () => {
    const store = draftStore(localStorage);
    store.set(draft);

    store.set(null);

    expect(store.get()).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it.each([["not json"], ['{"id": 1}']])("ignores a copy it cannot read: %s", (raw) => {
    localStorage.setItem(KEY, raw);

    expect(draftStore(localStorage).get()).toBeNull();
  });

  it("tells subscribers about changes until they unsubscribe", () => {
    const store = draftStore(localStorage);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    store.set(draft);
    unsubscribe();
    store.set(null);

    expect(listener).toHaveBeenCalledOnce();
  });
});
