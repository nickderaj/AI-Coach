// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Deps } from "./strategy";
import {
  CACHE_NAME,
  assetPaths,
  cacheFirst,
  dropOldCaches,
  networkFirst,
  precache,
  strategyFor,
} from "./strategy";

const ORIGIN = "https://app.test";

type FakeCache = Deps["cache"] & { entries: Map<string, string> };

function keyOf(request: RequestInfo | URL): string {
  if (typeof request === "string") {
    return request;
  }
  return request instanceof URL ? request.href : request.url;
}

/** A Cache keeping response bodies as text, keyed by URL. */
function fakeCache(initial: Record<string, string> = {}): FakeCache {
  const entries = new Map(Object.entries(initial));
  return {
    entries,
    match: (request): Promise<Response | undefined> => {
      const body = entries.get(keyOf(request));
      return Promise.resolve(body === undefined ? undefined : new Response(body));
    },
    put: async (request, response): Promise<void> => {
      entries.set(keyOf(request), await response.text());
    },
    keys: () => Promise.resolve([...entries.keys()].map((url) => new Request(url))),
    delete: (request) => Promise.resolve(entries.delete(keyOf(request))),
  };
}

function fetchFrom(
  routes: Record<string, Response | Error>,
): Deps["fetch"] & ReturnType<typeof vi.fn> {
  return vi.fn((request: Request) => {
    const reply = routes[request.url];
    if (reply === undefined) {
      return Promise.resolve(new Response("missing", { status: 404 }));
    }
    return reply instanceof Error ? Promise.reject(reply) : Promise.resolve(reply.clone());
  });
}

const get = (path: string): Request => new Request(`${ORIGIN}${path}`);

afterEach(() => {
  vi.useRealTimers();
});

describe("strategyFor", () => {
  it.each([
    ["GET", "/assets/app-abc.js", "cache-first"],
    ["GET", "/", "network-first"],
    ["GET", "/api/workouts?limit=500", "network-first"],
    ["GET", "/manifest.webmanifest", "network-first"],
    ["GET", "/api/assets/1", "network-first"],
    ["PUT", "/api/sets/abc", "bypass"],
    ["DELETE", "/api/workouts/abc", "bypass"],
  ])("%s %s is %s", (method, path, strategy) => {
    expect(strategyFor(method, new URL(`${ORIGIN}${path}`), ORIGIN)).toBe(strategy);
  });

  it("leaves other sites alone", () => {
    expect(strategyFor("GET", new URL("https://other.test/assets/x.js"), ORIGIN)).toBe("bypass");
  });
});

describe("cacheFirst", () => {
  it("answers from the cache without the network", async () => {
    const cache = fakeCache({ [`${ORIGIN}/assets/a.js`]: "cached" });
    const fetch = fetchFrom({});

    const response = await cacheFirst(get("/assets/a.js"), { cache, fetch });

    expect(await response.text()).toBe("cached");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("fetches and keeps what is missing", async () => {
    const cache = fakeCache();
    const fetch = fetchFrom({ [`${ORIGIN}/assets/a.js`]: new Response("fresh") });

    const response = await cacheFirst(get("/assets/a.js"), { cache, fetch });

    expect(await response.text()).toBe("fresh");
    expect(cache.entries.get(`${ORIGIN}/assets/a.js`)).toBe("fresh");
  });

  it("does not keep errors", async () => {
    const cache = fakeCache();

    const response = await cacheFirst(get("/assets/gone.js"), { cache, fetch: fetchFrom({}) });

    expect(response.status).toBe(404);
    expect(cache.entries.size).toBe(0);
  });
});

describe("networkFirst", () => {
  const page = { navigation: false, timeoutMs: 3000 };

  it("answers from the network and keeps a copy", async () => {
    const cache = fakeCache({ [`${ORIGIN}/api/workouts`]: "old" });
    const fetch = fetchFrom({ [`${ORIGIN}/api/workouts`]: new Response("new") });

    const answer = networkFirst(get("/api/workouts"), { cache, fetch }, page);

    expect(await (await answer.response).text()).toBe("new");
    await answer.done;
    expect(cache.entries.get(`${ORIGIN}/api/workouts`)).toBe("new");
  });

  it("falls back to the copy when offline", async () => {
    const cache = fakeCache({ [`${ORIGIN}/api/workouts`]: "old" });
    const fetch = fetchFrom({ [`${ORIGIN}/api/workouts`]: new TypeError("offline") });

    const answer = networkFirst(get("/api/workouts"), { cache, fetch }, page);

    expect(await (await answer.response).text()).toBe("old");
    await expect(answer.done).resolves.toBeUndefined();
  });

  it("falls back to the copy when the server is down behind the proxy", async () => {
    const cache = fakeCache({ [`${ORIGIN}/api/workouts`]: "old" });
    const fetch = fetchFrom({ [`${ORIGIN}/api/workouts`]: new Response("", { status: 502 }) });

    const answer = networkFirst(get("/api/workouts"), { cache, fetch }, page);

    expect(await (await answer.response).text()).toBe("old");
    await answer.done;
    expect(cache.entries.get(`${ORIGIN}/api/workouts`)).toBe("old");
  });

  it("passes on a client error rather than stale data", async () => {
    const cache = fakeCache({ [`${ORIGIN}/api/workouts/9`]: "old" });
    const fetch = fetchFrom({});

    const answer = networkFirst(get("/api/workouts/9"), { cache, fetch }, page);

    expect((await answer.response).status).toBe(404);
  });

  it("fails like the network when there is no copy", async () => {
    const fetch = fetchFrom({ [`${ORIGIN}/api/workouts`]: new TypeError("offline") });

    const answer = networkFirst(get("/api/workouts"), { cache: fakeCache(), fetch }, page);

    await expect(answer.response).rejects.toThrow("offline");
  });

  it("stops waiting for a slow network but still keeps its answer", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    const cache = fakeCache({ [`${ORIGIN}/api/workouts`]: "old" });
    let arrive: (response: Response) => void = () => undefined;
    const fetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          arrive = resolve;
        }),
    );

    const answer = networkFirst(get("/api/workouts"), { cache, fetch }, page);
    await vi.advanceTimersByTimeAsync(2999);
    let settled = false;
    void answer.response.then(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);

    expect(await (await answer.response).text()).toBe("old");
    arrive(new Response("new"));
    await answer.done;
    expect(cache.entries.get(`${ORIGIN}/api/workouts`)).toBe("new");
  });

  it("opens any screen offline from the cached app shell", async () => {
    const cache = fakeCache({ [`${ORIGIN}/`]: "<html>shell</html>" });
    const fetch = fetchFrom({ [`${ORIGIN}/?source=pwa`]: new TypeError("offline") });

    const answer = networkFirst(
      get("/?source=pwa"),
      { cache, fetch },
      { navigation: true, timeoutMs: 3000 },
    );

    expect(await (await answer.response).text()).toBe("<html>shell</html>");
  });

  it("does not use the app shell for data", async () => {
    const cache = fakeCache({ [`${ORIGIN}/`]: "<html>shell</html>" });
    const fetch = fetchFrom({ [`${ORIGIN}/api/workouts`]: new TypeError("offline") });

    const answer = networkFirst(get("/api/workouts"), { cache, fetch }, page);

    await expect(answer.response).rejects.toThrow("offline");
  });
});

const SHELL = `<!doctype html><html><head>
<script type="module" crossorigin src="/assets/app-new.js"></script>
<link rel="stylesheet" crossorigin href="/assets/app-new.css">
<link rel="manifest" href="/manifest.webmanifest" />
<link rel="modulepreload" href="/assets/app-new.js">
</head></html>`;

describe("assetPaths", () => {
  it("lists each built asset once and nothing else", () => {
    expect(assetPaths(SHELL)).toEqual(["/assets/app-new.js", "/assets/app-new.css"]);
  });
});

describe("precache", () => {
  it("keeps the shell and its assets and forgets older builds", async () => {
    const cache = fakeCache({
      [`${ORIGIN}/assets/app-old.js`]: "old js",
      [`${ORIGIN}/api/workouts`]: "data",
    });
    const fetch = fetchFrom({
      [`${ORIGIN}/`]: new Response(SHELL),
      [`${ORIGIN}/assets/app-new.js`]: new Response("new js"),
      [`${ORIGIN}/assets/app-new.css`]: new Response("new css"),
    });

    await precache({ cache, fetch }, ORIGIN);

    expect(Object.fromEntries(cache.entries)).toEqual({
      [`${ORIGIN}/`]: SHELL,
      [`${ORIGIN}/assets/app-new.js`]: "new js",
      [`${ORIGIN}/assets/app-new.css`]: "new css",
      [`${ORIGIN}/api/workouts`]: "data",
    });
    expect(at0(fetch).cache).toBe("reload");
  });

  it("fails the install when the shell cannot be fetched", async () => {
    const cache = fakeCache();
    const fetch = fetchFrom({ [`${ORIGIN}/`]: new Response("", { status: 403 }) });

    await expect(precache({ cache, fetch }, ORIGIN)).rejects.toThrow("the app shell answered 403");
    expect(cache.entries.size).toBe(0);
  });

  it("fails the install when an asset is missing, keeping the old shell", async () => {
    const cache = fakeCache({ [`${ORIGIN}/`]: "old shell" });
    const fetch = fetchFrom({ [`${ORIGIN}/`]: new Response(SHELL) });

    await expect(precache({ cache, fetch }, ORIGIN)).rejects.toThrow(
      "/assets/app-new.js answered 404",
    );
    expect(cache.entries.get(`${ORIGIN}/`)).toBe("old shell");
  });
});

function at0(fetch: ReturnType<typeof vi.fn>): Request {
  const [call] = fetch.mock.calls;
  const request: unknown = call?.[0];
  if (!(request instanceof Request)) {
    throw new Error("expected a fetched Request");
  }
  return request;
}

describe("dropOldCaches", () => {
  it("deletes every cache but the current one", async () => {
    const names = new Set(["trainer-v0", CACHE_NAME, "other"]);
    const storage = {
      keys: (): Promise<string[]> => Promise.resolve([...names]),
      delete: (name: string): Promise<boolean> => Promise.resolve(names.delete(name)),
    };

    await dropOldCaches(storage);

    expect([...names]).toEqual([CACHE_NAME]);
  });
});
