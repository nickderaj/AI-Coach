/**
 * The service worker: wires the browser's events to `strategy.ts`, where all the
 * decisions (and their tests) live. Built to `/sw.js`, outside `/assets/`, so its
 * scope is the whole app.
 */
import {
  CACHE_NAME,
  NETWORK_TIMEOUT_MS,
  cacheFirst,
  dropOldCaches,
  networkFirst,
  precache,
  strategyFor,
} from "./strategy";
import type { Deps } from "./strategy";

declare const self: ServiceWorkerGlobalScope;

async function deps(): Promise<Deps> {
  return { cache: await caches.open(CACHE_NAME), fetch: (request) => fetch(request) };
}

self.addEventListener("install", (event) => {
  // A new version takes over at once; built assets are content-hashed, so a
  // page from the previous build keeps working.
  event.waitUntil(
    deps()
      .then((d) => precache(d, self.location.origin))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(dropOldCaches(caches).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  switch (strategyFor(request.method, new URL(request.url), self.location.origin, request.cache)) {
    case "bypass":
      return;
    case "cache-first":
      event.respondWith(deps().then((d) => cacheFirst(request, d)));
      return;
    case "network-first": {
      const answer = deps().then((d) =>
        networkFirst(request, d, {
          navigation: request.mode === "navigate",
          timeoutMs: NETWORK_TIMEOUT_MS,
        }),
      );
      event.respondWith(answer.then((a) => a.response));
      event.waitUntil(answer.then((a) => a.done));
      return;
    }
  }
});
