import { z } from "zod";

import type { OutboxStore, QueuedWrite, RejectedWrite, Write } from "./store";

/** @internal Exported for tests; screens read it through `Outbox.status`. */
export interface OutboxStatus {
  /** Writes saved on the phone but not yet on the server. */
  pending: number;
  /** Writes the server refused, until dismissed. */
  rejected: RejectedWrite[];
  /** The last attempt could not reach the server; it will try again. */
  offline: boolean;
}

export interface Outbox {
  /** Save a write on the phone and start sending it; resolves once it is saved. */
  send: (write: Write) => Promise<void>;
  /** Send queued writes in order until the queue is empty or the server is unreachable. */
  flush: () => Promise<void>;
  /** Resolves once nothing is being sent (a retry may still be scheduled). */
  idle: () => Promise<void>;
  dismissRejected: () => Promise<void>;
  subscribe: (listener: () => void) => () => void;
  status: () => OutboxStatus;
  /** Retry when the phone comes back online or the app is reopened; returns a stop function. */
  start: () => () => void;
}

/** @internal Exported for tests. */
export const FIRST_RETRY_MS = 2_000;
/** @internal Exported for tests. */
export const MAX_RETRY_MS = 60_000;
/** @internal Exported for tests. */
export const DELIVERY_TIMEOUT_MS = 20_000;

type Delivery = { kind: "sent" } | { kind: "retry" } | { kind: "rejected"; reason: string };

/** Worth retrying: the server or something in front of it is struggling, not refusing. */
function transient(status: number): boolean {
  return status === 408 || status === 429 || status >= 500;
}

const errorBody = z.object({ detail: z.unknown() });

async function reasonFrom(response: Response): Promise<string> {
  const text = await response.text();
  let detail: unknown = text;
  try {
    const parsed = errorBody.safeParse(JSON.parse(text));
    detail = parsed.success ? parsed.data.detail : text;
  } catch {
    // Not JSON: use the text as it is.
  }
  const words = typeof detail === "string" ? detail : JSON.stringify(detail);
  return words === "" ? `The server answered ${String(response.status)}` : words;
}

async function exchange(write: QueuedWrite, signal: AbortSignal): Promise<Delivery> {
  const response = await fetch(write.path, {
    method: write.method,
    headers: { "Content-Type": "application/json" },
    body: write.method === "PUT" ? JSON.stringify(write.body) : null,
    signal,
  });
  if (response.ok) {
    return { kind: "sent" };
  }
  if (transient(response.status)) {
    return { kind: "retry" };
  }
  return { kind: "rejected", reason: await reasonFrom(response) };
}

/**
 * Send one write, giving up after `DELIVERY_TIMEOUT_MS`: `fetch` has no timeout
 * of its own, and a half-open connection would otherwise hold up the queue for
 * good. A write that timed out may still have reached the server; sending it
 * again is harmless because writes are idempotent.
 */
async function deliver(write: QueuedWrite): Promise<Delivery> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timedOut = new Promise<Delivery>((resolve) => {
    timer = setTimeout(() => {
      controller.abort();
      resolve({ kind: "retry" });
    }, DELIVERY_TIMEOUT_MS);
  });
  try {
    return await Promise.race([exchange(write, controller.signal), timedOut]);
  } catch {
    return { kind: "retry" };
  } finally {
    clearTimeout(timer);
  }
}

/** Runs `task` while holding the outbox lock. */
export type OutboxLock = (task: () => Promise<void>) => Promise<void>;

/**
 * One delivery at a time across every tab and the installed app on this phone,
 * which all share the queue: without it, an older in-flight write could land
 * after a newer one and overwrite it. Where Web Locks are missing (iOS before
 * 15.4) the app still works, one context at a time being the only protection.
 */
export function webLock(locks: LockManager | undefined): OutboxLock {
  if (locks === undefined) {
    return (task) => task();
  }
  return (task) => locks.request("trainer-outbox", task);
}

export function createOutbox(store: OutboxStore, lock: OutboxLock): Outbox {
  let snapshot: OutboxStatus = { pending: 0, rejected: [], offline: false };
  const listeners = new Set<() => void>();
  let running: Promise<void> | undefined;
  let again = false;
  let delay = FIRST_RETRY_MS;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function refresh(offline = snapshot.offline): Promise<void> {
    snapshot = { pending: await store.pending(), rejected: await store.rejected(), offline };
    for (const listener of listeners) {
      listener();
    }
  }

  function retryLater(): void {
    clearTimeout(timer);
    timer = setTimeout(() => {
      void flush();
    }, delay);
    delay = Math.min(delay * 2, MAX_RETRY_MS);
  }

  async function drain(): Promise<void> {
    for (let write = await store.next(); write !== undefined; write = await store.next()) {
      const delivery = await deliver(write);
      if (delivery.kind === "retry") {
        retryLater();
        await refresh(true);
        return;
      }
      await store.finish(write, delivery.kind === "rejected" ? delivery.reason : null);
      await refresh(false);
    }
    clearTimeout(timer);
    delay = FIRST_RETRY_MS;
    await refresh(false);
  }

  function flush(): Promise<void> {
    if (running !== undefined) {
      // A write may have been queued after the running drain last looked.
      again = true;
      return running;
    }
    running = lock(drain).finally(() => {
      running = undefined;
      if (again) {
        again = false;
        void flush();
      }
    });
    return running;
  }

  return {
    async send(write): Promise<void> {
      await store.add(write);
      await refresh();
      void flush();
    },
    flush,
    async idle(): Promise<void> {
      while (running !== undefined) {
        await running;
      }
    },
    async dismissRejected(): Promise<void> {
      await store.dismissRejected();
      await refresh();
    },
    subscribe(listener): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    status: () => snapshot,
    start(): () => void {
      const onOnline = (): void => {
        void flush();
      };
      const onVisible = (): void => {
        if (document.visibilityState === "visible") {
          void flush();
        }
      };
      window.addEventListener("online", onOnline);
      document.addEventListener("visibilitychange", onVisible);
      void flush();
      return () => {
        window.removeEventListener("online", onOnline);
        document.removeEventListener("visibilitychange", onVisible);
        clearTimeout(timer);
      };
    },
  };
}
