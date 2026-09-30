import { vi } from "vitest";

type Reply = { status?: number; body: unknown } | Error;

/** Replace global fetch with a router from URL path to canned replies. */
export function mockFetch(routes: Record<string, Reply>): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
    const path =
      typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const reply = routes[path];
    if (reply === undefined) {
      return Promise.resolve(new Response("{}", { status: 404 }));
    }
    if (reply instanceof Error) {
      return Promise.reject(reply);
    }
    return Promise.resolve(
      new Response(JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** `items[index]`, failing the test if it is missing. */
export function at<T>(items: T[], index: number): T {
  const item = items[index];
  if (item === undefined) {
    throw new Error(`expected an item at index ${String(index)}`);
  }
  return item;
}

export const set = (
  set_number: number,
  reps: number | null,
  load_kg: number | null,
  extra: { duration_s?: number; rpe?: number; notes?: string } = {},
): Record<string, unknown> => ({
  set_number,
  reps,
  load_kg,
  duration_s: extra.duration_s ?? null,
  rpe: extra.rpe ?? null,
  notes: extra.notes ?? null,
});
