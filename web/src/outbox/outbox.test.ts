import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Outbox } from "./outbox";
import { FIRST_RETRY_MS, MAX_RETRY_MS, createOutbox } from "./outbox";
import type { OutboxStore, Write } from "./store";
import { outboxStore } from "./store";

const put = (path: string, body: unknown = { reps: 8 }): Write => ({
  method: "PUT",
  path,
  body,
  label: `Save ${path}`,
});

let store: OutboxStore;
let outbox: Outbox;
let fetchMock: ReturnType<typeof vi.fn>;

/** Answer fetches in turn; `Error`s are thrown like a network failure. */
function replies(...answers: (Response | Error)[]): void {
  for (const answer of answers) {
    if (answer instanceof Error) {
      fetchMock.mockRejectedValueOnce(answer);
    } else {
      fetchMock.mockResolvedValueOnce(answer);
    }
  }
}

const ok = (): Response => new Response("{}", { status: 200 });
const refused = (status: number, body: string): Response => new Response(body, { status });

function sent(): [string, string | undefined, unknown][] {
  return (fetchMock.mock.calls as [string, RequestInit][]).map(([path, init]) => [
    path,
    init.method,
    init.body,
  ]);
}

const idle = (): Promise<void> => outbox.idle();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  store = outboxStore(new IDBFactory());
  outbox = createOutbox(store);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("send", () => {
  it("delivers a PUT with its JSON body", async () => {
    replies(ok());

    await outbox.send(put("/api/sets/a", { reps: 10 }));
    await idle();

    expect(fetchMock).toHaveBeenCalledWith("/api/sets/a", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: '{"reps":10}',
    });
    expect(outbox.status()).toEqual({ pending: 0, rejected: [], offline: false });
  });

  it("delivers a DELETE without a body", async () => {
    replies(new Response(null, { status: 204 }));

    await outbox.send({ method: "DELETE", path: "/api/sets/a", body: null, label: "Delete" });
    await idle();

    expect(sent()).toEqual([["/api/sets/a", "DELETE", null]]);
    expect(await store.pending()).toBe(0);
  });

  it("has the write saved on the phone before it resolves", async () => {
    fetchMock.mockReturnValue(new Promise(() => undefined)); // the server never answers
    const listener = vi.fn();
    outbox.subscribe(listener);

    await outbox.send(put("/api/sets/a"));

    expect(await store.pending()).toBe(1);
    expect(outbox.status().pending).toBe(1);
    expect(listener).toHaveBeenCalled();
  });

  it("sends writes in the order they were made", async () => {
    replies(ok(), ok(), ok());

    await outbox.send(put("/api/workouts/w"));
    await outbox.send(put("/api/sets/a"));
    await outbox.send(put("/api/sets/b"));
    await idle();

    expect(sent().map(([path]) => path)).toEqual(["/api/workouts/w", "/api/sets/a", "/api/sets/b"]);
  });

  it("sends a write made while an earlier one is on its way", async () => {
    let answer: (response: Response) => void = () => undefined;
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        answer = resolve;
      }),
    );
    replies(ok());

    await outbox.send(put("/api/sets/a"));
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    await outbox.send(put("/api/sets/b"));
    answer(ok());
    await idle();

    expect(sent().map(([path]) => path)).toEqual(["/api/sets/a", "/api/sets/b"]);
    expect(outbox.status().pending).toBe(0);
  });
});

describe("when the server cannot be reached", () => {
  it("keeps the write and retries later, backing off", async () => {
    replies(new TypeError("offline"), refused(502, "bad gateway"), refused(429, ""), ok());

    await outbox.send(put("/api/sets/a"));
    await idle();

    expect(outbox.status()).toMatchObject({ pending: 1, offline: true });

    await vi.advanceTimersByTimeAsync(FIRST_RETRY_MS);
    await idle();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(FIRST_RETRY_MS * 2 - 1);
    await idle();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    await idle();
    expect(fetchMock).toHaveBeenCalledTimes(3);

    await vi.advanceTimersByTimeAsync(FIRST_RETRY_MS * 4);
    await idle();

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(outbox.status()).toEqual({ pending: 0, rejected: [], offline: false });
  });

  it("retries a request timeout", async () => {
    replies(refused(408, ""), ok());

    await outbox.send(put("/api/sets/a"));
    await idle();
    await vi.advanceTimersByTimeAsync(FIRST_RETRY_MS);
    await idle();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(outbox.status().pending).toBe(0);
  });

  it("waits at most a minute between tries", async () => {
    fetchMock.mockRejectedValue(new TypeError("offline"));

    await outbox.send(put("/api/sets/a"));
    await idle();
    for (let wait = FIRST_RETRY_MS; wait < MAX_RETRY_MS; wait *= 2) {
      await vi.advanceTimersByTimeAsync(wait);
      await idle();
    }
    const tries = fetchMock.mock.calls.length;

    await vi.advanceTimersByTimeAsync(MAX_RETRY_MS);
    await idle();

    expect(fetchMock).toHaveBeenCalledTimes(tries + 1);
  });

  it("starts again from a short wait once it gets through", async () => {
    replies(new TypeError("offline"), ok(), new TypeError("offline"), ok());

    await outbox.send(put("/api/sets/a"));
    await idle();
    await vi.advanceTimersByTimeAsync(FIRST_RETRY_MS);
    await idle();
    await outbox.send(put("/api/sets/b"));
    await idle();
    await vi.advanceTimersByTimeAsync(FIRST_RETRY_MS);
    await idle();

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(outbox.status().pending).toBe(0);
  });
});

describe("when the server refuses a write", () => {
  it.each([
    [refused(404, '{"detail":"no workout abc"}'), "no workout abc"],
    [refused(422, '{"detail":[{"msg":"too heavy"}]}'), '[{"msg":"too heavy"}]'],
    [refused(409, '{"other":1}'), '{"other":1}'],
    [refused(403, "Forbidden"), "Forbidden"],
    [refused(400, ""), "The server answered 400"],
  ])("records why and moves on (%#)", async (response, reason) => {
    replies(response, ok());

    await outbox.send(put("/api/sets/a"));
    await outbox.send(put("/api/sets/b"));
    await idle();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(outbox.status()).toEqual({
      pending: 0,
      rejected: [{ ...put("/api/sets/a"), id: 1, reason }],
      offline: false,
    });
  });

  it("forgets refused writes once dismissed", async () => {
    replies(refused(404, ""));
    await outbox.send(put("/api/sets/a"));
    await idle();
    const listener = vi.fn();
    const unsubscribe = outbox.subscribe(listener);

    await outbox.dismissRejected();

    expect(outbox.status().rejected).toEqual([]);
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    await outbox.dismissRejected();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("start", () => {
  it("sends what was left from last time", async () => {
    await store.add(put("/api/sets/a"));
    replies(ok());

    const stop = outbox.start();
    await idle();
    stop();

    expect(sent().map(([path]) => path)).toEqual(["/api/sets/a"]);
  });

  it("tries again when the phone is back online or the app is reopened", async () => {
    fetchMock.mockRejectedValue(new TypeError("offline"));
    const stop = outbox.start();
    await outbox.send(put("/api/sets/a"));
    await idle();
    const tries = fetchMock.mock.calls.length;

    window.dispatchEvent(new Event("online"));
    await idle();
    expect(fetchMock).toHaveBeenCalledTimes(tries + 1);

    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    await idle();
    expect(fetchMock).toHaveBeenCalledTimes(tries + 1);

    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await idle();
    expect(fetchMock).toHaveBeenCalledTimes(tries + 2);

    stop();
    window.dispatchEvent(new Event("online"));
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(MAX_RETRY_MS);
    await idle();
    expect(fetchMock).toHaveBeenCalledTimes(tries + 2);
  });
});
