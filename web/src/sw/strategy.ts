/**
 * What the service worker does with each request, kept free of worker globals
 * so it can be tested.
 *
 * - Built assets (`/assets/*`) have content hashes in their names, so a cached
 *   copy is always right: cache first.
 * - Everything else the app reads (the page, `/api` reads, the manifest and
 *   icons) is network first, falling back to the last copy when the network
 *   fails, answers 5xx or is too slow, so the app opens and shows recent data
 *   in a gym with no signal.
 * - Writes, other sites and reads that must be fresh (`cache: "no-store"`)
 *   are left alone; writes go through the outbox.
 */

/** Bump to discard every cached response when the worker is next updated. */
export const CACHE_NAME = "coach-v5";

/** The spoken rest countdown, needed on the first offline workout too. */
const REST_TRACK_PATH = "/rest-voice.m4a";

/** How long to wait for the network before answering from the cache. */
export const NETWORK_TIMEOUT_MS = 3_000;

export type Strategy = "cache-first" | "network-first" | "bypass";

type Cache = Pick<globalThis.Cache, "match" | "put" | "keys" | "delete">;
type Fetch = (request: Request) => Promise<Response>;

export interface Deps {
  cache: Cache;
  fetch: Fetch;
}

/**
 * A read made with `cache: "no-store"` must come from the server or fail: it
 * is left to the network, never answered from a stale copy.
 */
export function strategyFor(
  method: string,
  url: URL,
  origin: string,
  cache: RequestCache = "default",
): Strategy {
  if (method !== "GET" || url.origin !== origin || cache === "no-store") {
    return "bypass";
  }
  return url.pathname.startsWith("/assets/") || url.pathname === REST_TRACK_PATH
    ? "cache-first"
    : "network-first";
}

export async function cacheFirst(request: Request, deps: Deps): Promise<Response> {
  const cached = await deps.cache.match(request);
  if (cached !== undefined) {
    return rangeResponse(request, cached);
  }
  const response = await deps.fetch(request);
  if (response.ok && response.status !== 206) {
    await deps.cache.put(request, response.clone());
  }
  return response;
}

interface ByteRange {
  end: number;
  start: number;
}

function boundedRange(start: number, end: number, size: number): ByteRange | null {
  return start < size && start <= end ? { end, start } : null;
}

function suffixRange(last: string, size: number): ByteRange | null {
  const length = Number(last);
  return last === "" || length === 0 ? null : { start: Math.max(0, size - length), end: size - 1 };
}

function byteRange(value: string, size: number): ByteRange | null {
  const match = /^bytes=(\d*)-(\d*)$/.exec(value);
  if (match === null) {
    return null;
  }
  const first = match[1] ?? "";
  const last = match[2] ?? "";
  if (first === "") {
    return suffixRange(last, size);
  }
  const start = Number(first);
  const end = last === "" ? size - 1 : Math.min(Number(last), size - 1);
  return boundedRange(start, end, size);
}

async function rangeResponse(request: Request, response: Response): Promise<Response> {
  const requested = request.headers.get("Range");
  if (requested === null) {
    return response;
  }
  const body = await response.blob();
  const range = byteRange(requested, body.size);
  if (range === null) {
    return new Response(null, {
      status: 416,
      headers: { "Content-Range": `bytes */${String(body.size)}` },
    });
  }
  const headers = new Headers(response.headers);
  headers.set("Accept-Ranges", "bytes");
  headers.set("Content-Length", String(range.end - range.start + 1));
  headers.set(
    "Content-Range",
    `bytes ${String(range.start)}-${String(range.end)}/${String(body.size)}`,
  );
  return new Response(body.slice(range.start, range.end + 1, body.type), {
    status: 206,
    statusText: "Partial Content",
    headers,
  });
}

export interface Answer {
  response: Promise<Response>;
  /** Settles once the network answer is cached, which may be after `response`. */
  done: Promise<unknown>;
}

/**
 * The network's answer, or the cached one if the network fails, answers 5xx or
 * takes longer than `timeoutMs`. A navigation falls back to the cached app shell (`/`), since
 * every screen is the same page.
 */
export function networkFirst(
  request: Request,
  deps: Deps,
  options: { navigation: boolean; timeoutMs: number },
): Answer {
  const network = deps.fetch(request).then(async (response) => {
    if (response.ok) {
      await deps.cache.put(request, response.clone());
    }
    return response;
  });
  const cachedCopy = (async (): Promise<Response | undefined> =>
    (await deps.cache.match(request)) ??
    (options.navigation ? deps.cache.match(new URL("/", request.url).href) : undefined))();

  const response = cachedCopy.then((cached) => {
    if (cached === undefined) {
      return network;
    }
    // A 5xx usually means the app is down behind a proxy that is up: as good as offline.
    const fallback = network.then(
      (fresh) => (fresh.status >= 500 ? cached : fresh),
      () => cached,
    );
    const slow = new Promise<Response>((resolve) => {
      setTimeout(() => {
        resolve(cached);
      }, options.timeoutMs);
    });
    return Promise.race([fallback, slow]);
  });
  return { response, done: network.catch(() => undefined) };
}

/**
 * Same-origin `/assets/` files that a built `index.html` loads.
 *
 * @internal Exported for tests; the worker uses `precache`.
 */
export function assetPaths(html: string): string[] {
  const paths = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((match) => match[1]);
  return [...new Set(paths.filter((path) => path !== undefined))];
}

/**
 * Cache the app shell and the assets it loads, then forget assets from older
 * builds, so the app opens offline straight after it is installed or updated.
 */
export async function precache(deps: Deps, origin: string): Promise<void> {
  const shell = await deps.fetch(new Request(`${origin}/`, { cache: "reload" }));
  if (!shell.ok) {
    throw new Error(`the app shell answered ${String(shell.status)}`);
  }
  const assets = [...assetPaths(await shell.clone().text()), REST_TRACK_PATH];
  for (const path of assets) {
    const response = await deps.fetch(new Request(`${origin}${path}`));
    if (!response.ok) {
      throw new Error(`${path} answered ${String(response.status)}`);
    }
    await deps.cache.put(`${origin}${path}`, response);
  }
  await deps.cache.put(`${origin}/`, shell);

  const current = new Set(assets);
  for (const cached of await deps.cache.keys()) {
    const path = new URL(cached.url).pathname;
    if (path.startsWith("/assets/") && !current.has(path)) {
      await deps.cache.delete(cached);
    }
  }
}

/** Delete caches left by earlier versions of the worker. */
export async function dropOldCaches(storage: Pick<CacheStorage, "keys" | "delete">): Promise<void> {
  for (const name of await storage.keys()) {
    if (name !== CACHE_NAME) {
      await storage.delete(name);
    }
  }
}
