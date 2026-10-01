import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it } from "vitest";

import type { OutboxStore, QueuedWrite, Write } from "./store";
import { outboxStore } from "./store";

const put = (path: string, body: unknown = { n: 1 }): Write => ({
  method: "PUT",
  path,
  body,
  label: `save ${path}`,
});
const del = (path: string): Write => ({
  method: "DELETE",
  path,
  body: null,
  label: `delete ${path}`,
});

let factory: IDBFactory;
let store: OutboxStore;

beforeEach(() => {
  factory = new IDBFactory();
  store = outboxStore(factory);
});

async function queued(): Promise<[string, string, unknown][]> {
  const seen: [string, string, unknown][] = [];
  for (let write = await store.next(); write !== undefined; write = await store.next()) {
    seen.push([write.method, write.path, write.body]);
    await store.finish(write, null);
  }
  return seen;
}

async function head(): Promise<QueuedWrite> {
  const write = await store.next();
  if (write === undefined) {
    throw new Error("expected a queued write");
  }
  return write;
}

describe("outboxStore", () => {
  it("is empty to begin with", async () => {
    expect(await store.next()).toBeUndefined();
    expect(await store.pending()).toBe(0);
    expect(await store.rejected()).toEqual([]);
  });

  it("keeps writes in the order they were made", async () => {
    await store.add(put("/api/workouts/w"));
    await store.add(put("/api/sets/a"));
    await store.add(del("/api/sets/b"));

    expect(await store.pending()).toBe(3);
    expect(await head()).toEqual({ ...put("/api/workouts/w"), id: 1, revision: 0 });
    expect(await queued()).toEqual([
      ["PUT", "/api/workouts/w", { n: 1 }],
      ["PUT", "/api/sets/a", { n: 1 }],
      ["DELETE", "/api/sets/b", null],
    ]);
    expect(await store.pending()).toBe(0);
  });

  it("replaces a queued PUT in place, so the workout is still created first", async () => {
    await store.add(put("/api/workouts/w", { ended_at: null }));
    await store.add(put("/api/sets/a"));
    await store.add(put("/api/workouts/w", { ended_at: "later" }));

    expect(await store.pending()).toBe(2);
    expect((await head()).revision).toBe(1);
    expect(await queued()).toEqual([
      ["PUT", "/api/workouts/w", { ended_at: "later" }],
      ["PUT", "/api/sets/a", { n: 1 }],
    ]);
  });

  it("sends a DELETE after the writes queued before it", async () => {
    await store.add(put("/api/workouts/w"));
    await store.add(put("/api/sets/a"));
    await store.add(del("/api/workouts/w"));

    expect(await queued()).toEqual([
      ["PUT", "/api/sets/a", { n: 1 }],
      ["DELETE", "/api/workouts/w", null],
    ]);
  });

  it("lets a PUT take the place of a queued DELETE", async () => {
    await store.add(del("/api/sets/a"));
    await store.add(put("/api/sets/a"));

    expect(await queued()).toEqual([["PUT", "/api/sets/a", { n: 1 }]]);
  });

  it("keeps a write that was replaced while it was being sent", async () => {
    await store.add(put("/api/sets/a", { reps: 8 }));
    const inFlight = await head();
    await store.add(put("/api/sets/a", { reps: 10 }));

    await store.finish(inFlight, null);

    expect(await queued()).toEqual([["PUT", "/api/sets/a", { reps: 10 }]]);
  });

  it("ignores finishing a write that a DELETE already dropped", async () => {
    await store.add(put("/api/sets/a"));
    const inFlight = await head();
    await store.add(del("/api/sets/a"));

    await store.finish(inFlight, "refused");

    expect(await store.rejected()).toEqual([]);
    expect(await queued()).toEqual([["DELETE", "/api/sets/a", null]]);
  });

  it("keeps refused writes until they are dismissed", async () => {
    await store.add(put("/api/sets/a", { reps: 8 }));
    await store.add(put("/api/sets/b"));

    await store.finish(await head(), "workout not found");

    expect(await store.rejected()).toEqual([
      { ...put("/api/sets/a", { reps: 8 }), id: 1, reason: "workout not found" },
    ]);
    expect(await store.pending()).toBe(1);

    await store.dismissRejected();

    expect(await store.rejected()).toEqual([]);
    expect(await store.pending()).toBe(1);
  });

  it("finds the write queued for a path", async () => {
    await store.add(put("/api/profile", { bodyweight_kg: 70 }));
    await store.add(put("/api/sets/a"));

    expect(await store.queued("/api/profile")).toMatchObject({
      path: "/api/profile",
      body: { bodyweight_kg: 70 },
    });
    expect(await store.queued("/api/workouts/w")).toBeUndefined();
  });

  it("survives the app being closed", async () => {
    await store.add(put("/api/sets/a"));

    store = outboxStore(factory);

    expect(await queued()).toEqual([["PUT", "/api/sets/a", { n: 1 }]]);
  });

  it("reports a database it cannot open", async () => {
    const newer = factory.open("trainer", 2);
    await new Promise((resolve) => {
      newer.onsuccess = (): void => {
        newer.result.close();
        resolve(undefined);
      };
    });

    await expect(store.pending()).rejects.toThrow(/version/i);
  });
});
