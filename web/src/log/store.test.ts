import { afterEach, describe, expect, it, vi } from "vitest";

import { addBlock, newDraft, updateSet } from "./draft";
import type { Draft } from "./draft";
import { draftStore } from "./store";

const KEY = "trainer.workout";
const draft = newDraft("w", new Date("2026-09-30T08:00:00Z"));

/** A second tab: same storage, its own window for events. */
const otherTab = (): EventTarget => new EventTarget();

function withBlock(current: Draft): Draft {
  return addBlock(
    current,
    { block: "b", set: "s1" },
    { id: 7, name: "Bench", measure: "reps", equipment: null },
    [],
  );
}

afterEach(() => {
  localStorage.clear();
});

describe("draftStore", () => {
  it("has nothing when no workout is in progress", () => {
    expect(draftStore(localStorage, window).get()).toBeNull();
  });

  it("keeps the workout across app launches", () => {
    draftStore(localStorage, window).set(draft);

    expect(draftStore(localStorage, window).get()).toEqual(draft);
  });

  it("forgets a finished workout", () => {
    const store = draftStore(localStorage, window);
    store.set(draft);

    store.set(null);

    expect(store.get()).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it.each([["not json"], ['{"id": 1}']])("ignores a copy it cannot read: %s", (raw) => {
    localStorage.setItem(KEY, raw);

    expect(draftStore(localStorage, window).get()).toBeNull();
    expect(localStorage.getItem(KEY)).toBe(raw);
  });

  it("puts a correction the app was closed in the middle of back to what was sent", () => {
    const sent = { kg: "60", reps: "8", seconds: "" };
    const halfEdited = updateSet(withBlock(draft), "b", "s1", {
      kg: "60",
      reps: "",
      logged: sent,
    });
    localStorage.setItem(KEY, JSON.stringify(halfEdited));

    const reopened = draftStore(localStorage, window).get();

    expect(reopened?.blocks[0]?.sets[0]).toMatchObject({ reps: "8", logged: sent });
    expect(JSON.parse(localStorage.getItem(KEY) ?? "null")).toEqual(reopened);
  });

  it("tells subscribers about changes until they unsubscribe", () => {
    const store = draftStore(localStorage, window);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    store.set(draft);
    unsubscribe();
    store.set(null);

    expect(listener).toHaveBeenCalledOnce();
  });

  it("returns what an update made", () => {
    const store = draftStore(localStorage, window);

    expect(store.update((current) => current ?? draft)).toEqual(draft);
    expect(store.update((current) => (current === null ? null : { ...current, id: "x" }))).toEqual({
      ...draft,
      id: "x",
    });
  });
});

describe("with the app open in two tabs", () => {
  it("builds on the other tab's workout instead of starting a second one", () => {
    const first = draftStore(localStorage, otherTab());
    const second = draftStore(localStorage, otherTab());
    const mine = newDraft("mine", new Date("2026-09-30T09:00:00Z"));

    first.update((current) => current ?? draft);
    const result = second.update((current) => current ?? mine);

    expect(result).toEqual(draft);
    expect(second.get()).toEqual(draft);
  });

  it("does not lose the other tab's changes when making its own", () => {
    const first = draftStore(localStorage, otherTab());
    const second = draftStore(localStorage, otherTab());
    first.set(draft);
    second.update((current) => current);

    first.update((current) => (current === null ? null : { ...current, restUntil: 5 }));
    second.update((current) => (current === null ? null : withBlock(current)));

    expect(second.get()).toEqual({ ...withBlock(draft), restUntil: 5 });
  });

  it("shows the other tab's changes as they happen", () => {
    const events = otherTab();
    const watching = draftStore(localStorage, events);
    const listener = vi.fn();
    const unsubscribe = watching.subscribe(listener);
    const storageEvent = (key: string | null): Event =>
      Object.assign(new Event("storage"), { key });

    localStorage.setItem(KEY, JSON.stringify(draft)); // as the other tab would
    events.dispatchEvent(storageEvent("unrelated"));
    expect(watching.get()).toBeNull();

    events.dispatchEvent(storageEvent(KEY));
    expect(watching.get()).toEqual(draft);

    localStorage.clear(); // clearing all storage reports no key
    events.dispatchEvent(storageEvent(null));
    expect(watching.get()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    localStorage.setItem(KEY, JSON.stringify(draft));
    events.dispatchEvent(storageEvent(KEY));
    expect(watching.get()).toBeNull();
  });
});
