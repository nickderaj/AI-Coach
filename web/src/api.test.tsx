import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import {
  ApiError,
  OFFLINE_CREATE,
  askCoach,
  createExercise,
  fetchJson,
  readAllNotices,
  seeNotice,
  useApi,
} from "./api";
import type { NewExercise } from "./api";
import { mockFetch } from "./test/fetch";

const schema = z.object({ value: z.number() });

describe("fetchJson", () => {
  it("returns the validated body", async () => {
    const fetchMock = mockFetch({ "/api/x": { body: { value: 1 } } });

    await expect(fetchJson("/api/x", schema)).resolves.toEqual({ value: 1 });
    expect(fetchMock).toHaveBeenCalledWith("/api/x", {
      signal: null,
      headers: { Accept: "application/json" },
    });
  });

  it("passes the abort signal through", async () => {
    const fetchMock = mockFetch({ "/api/x": { body: { value: 1 } } });
    const controller = new AbortController();

    await fetchJson("/api/x", schema, controller.signal);

    expect(fetchMock).toHaveBeenCalledWith("/api/x", {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
  });

  it("raises ApiError with a readable message", async () => {
    mockFetch({ "/api/gone": { status: 404, body: {} }, "/api/boom": { status: 503, body: {} } });

    await expect(fetchJson("/api/gone", schema)).rejects.toMatchObject({
      status: 404,
      message: "Not found",
      name: "ApiError",
    });
    await expect(fetchJson("/api/boom", schema)).rejects.toThrow("The server answered 503");
  });

  it("rejects a body that does not match the schema", async () => {
    mockFetch({ "/api/x": { body: { value: "one" } } });

    await expect(fetchJson("/api/x", schema)).rejects.toBeInstanceOf(z.ZodError);
  });
});

function Probe({ path }: { path: string }): ReactElement {
  const state = useApi(path, schema);
  return <output>{JSON.stringify(state)}</output>;
}

describe("useApi", () => {
  it("starts loading, then shows the data", async () => {
    mockFetch({ "/api/x": { body: { value: 7 } } });

    render(<Probe path="/api/x" />);

    expect(screen.getByRole("status")).toHaveTextContent('{"status":"loading"}');
    expect(await screen.findByText('{"status":"ready","data":{"value":7}}')).toBeInTheDocument();
  });

  it.each([
    [{ status: 404, body: {} }, "Not found"],
    [{ body: { value: "x" } }, "The server sent data this app does not understand"],
    [new TypeError("Failed to fetch"), "Could not reach the server"],
  ])("describes failures (%#)", async (reply, message) => {
    mockFetch({ "/api/x": reply });

    render(<Probe path="/api/x" />);

    expect(
      await screen.findByText(JSON.stringify({ status: "error", message })),
    ).toBeInTheDocument();
  });

  it("ignores a response that arrives after unmounting", async () => {
    let reject: (reason: unknown) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((_, rejectWith) => {
            reject = rejectWith;
          }),
      ),
    );
    const errors = vi.spyOn(console, "error");

    const { unmount } = render(<Probe path="/api/x" />);
    unmount();
    reject(new DOMException("aborted", "AbortError"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(errors).not.toHaveBeenCalled();
  });

  it("exposes ApiError status", () => {
    expect(new ApiError(500).status).toBe(500);
  });
});

describe("mockFetch", () => {
  it("routes URL and Request inputs by path", async () => {
    mockFetch({ "/api/x": { body: { value: 2 } } });

    const fromUrl = await fetch(new URL("http://localhost/api/x"));
    const fromRequest = await fetch(new Request("http://localhost/api/x"));

    expect(fromUrl.status).toBe(200);
    expect(fromRequest.status).toBe(404); // Request.url is absolute, so it is not a route key
  });

  it("fails loudly for a missing index", async () => {
    const { at } = await import("./test/fetch");

    expect(() => at([], 0)).toThrow("expected an item at index 0");
  });
});

describe("createExercise", () => {
  const request: NewExercise = {
    name: "Zercher Squat",
    equipment: "barbell",
    measure: "reps",
    allow_similar: false,
  };
  const created = {
    id: 50,
    name: "Zercher Squat",
    equipment: "barbell",
    muscle_groups: null,
    measure: "reps",
    workouts: 0,
    last_done: null,
    best_load_kg: null,
  };

  it("posts the new exercise and returns it", async () => {
    const fetchMock = mockFetch({ "/api/exercises": { status: 201, body: created } });

    expect(await createExercise(request)).toEqual({ kind: "created", exercise: created });
    expect(fetchMock).toHaveBeenCalledWith("/api/exercises", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    });
  });

  it("returns the exercises it would duplicate", async () => {
    const matches = [{ id: 3, name: "Back Squat", equipment: "barbell" }];
    mockFetch({
      "/api/exercises": { status: 409, body: { detail: { reason: "similar", matches } } },
    });

    expect(await createExercise(request)).toEqual({
      kind: "duplicate",
      reason: "similar",
      matches,
    });
  });

  it.each([
    [{ status: 409, body: { detail: "busy" } }, "The server answered 409"],
    [{ status: 422, body: { detail: [] } }, "The server answered 422"],
    [{ status: 201, body: { id: "x" } }, "The server answered 201"],
  ])("reports anything else (%#)", async (reply, message) => {
    mockFetch({ "/api/exercises": reply });

    expect(await createExercise(request)).toEqual({ kind: "error", message });
  });

  it("reports a body that is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("Bad Gateway", { status: 502 }))),
    );

    expect(await createExercise(request)).toEqual({
      kind: "error",
      message: "The server answered 502",
    });
  });

  it("explains that it needs a connection", async () => {
    mockFetch({ "/api/exercises": new TypeError("offline") });

    expect(await createExercise(request)).toEqual({ kind: "error", message: OFFLINE_CREATE });
  });
});

describe("notices", () => {
  it("tells the server a notice was seen, and shrugs off a failure", async () => {
    const fetchMock = vi.fn(() => Promise.reject(new TypeError("offline")));
    vi.stubGlobal("fetch", fetchMock);

    await expect(seeNotice(5)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith("/api/inbox/5/seen", { method: "POST" });
  });

  it.each([
    [new Response(null, { status: 204 }), true],
    [new Response("{}", { status: 500 }), false],
    [new TypeError("offline"), false],
  ])("marks everything read (%#)", async (reply, done) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => (reply instanceof Error ? Promise.reject(reply) : Promise.resolve(reply))),
    );

    await expect(readAllNotices()).resolves.toBe(done);
  });

  it("takes a coach reply with or without its notice", async () => {
    const reply = { role: "assistant", text: "Hi.", at: "2026-10-01T13:14:31+00:00" };
    mockFetch({ "/api/coach/messages": { body: { ...reply, notice_id: 5 } } });
    await expect(askCoach("hi")).resolves.toEqual({
      kind: "ok",
      value: { ...reply, notice_id: 5 },
    });

    mockFetch({ "/api/coach/messages": { body: reply } });
    await expect(askCoach("hi")).resolves.toEqual({
      kind: "ok",
      value: { ...reply, notice_id: null },
    });
  });
});
