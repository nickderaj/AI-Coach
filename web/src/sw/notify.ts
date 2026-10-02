/**
 * What the service worker does with a push and a tap on its notification, kept
 * free of worker globals so it can be tested.
 *
 * Every push is shown: a browser may stop delivering pushes to a worker that
 * receives them without showing one (iOS does).
 */

/** What the server sends: the notice, and the screen of the app it opens. */
export interface PushMessage {
  id: number | null;
  title: string;
  body: string;
  route: string;
}

import type { OpenMessage } from "./message";

/** Only routes of this app are opened (as in `message.ts`). */
const ROUTE = /^#\/[a-z/]*$/;
const FALLBACK: PushMessage = { id: null, title: "Trainer", body: "", route: "#/inbox" };

function fields(data: unknown): Record<string, unknown> {
  return typeof data === "object" && data !== null ? (data as Record<string, unknown>) : {};
}

function noticeId(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function appRoute(value: unknown): string {
  return typeof value === "string" && ROUTE.test(value) ? value : FALLBACK.route;
}

function parse(json: string | null): unknown {
  try {
    return JSON.parse(json ?? "null");
  } catch {
    return null;
  }
}

/** Read a push's JSON; anything unexpected becomes a plain notice opening the inbox. */
export function readPush(json: string | null): PushMessage {
  const { id, title, body, route } = fields(parse(json));
  return {
    id: noticeId(id),
    title: text(title) || FALLBACK.title,
    body: text(body),
    route: appRoute(route),
  };
}

/** What a notification remembers, to act on a tap. */
export interface Tapped {
  id: number | null;
  route: string;
}

/** The notification to show for `message`. */
export function notificationFor(message: PushMessage): {
  title: string;
  options: NotificationOptions;
} {
  const data: Tapped = { id: message.id, route: message.route };
  return {
    title: message.title,
    options: {
      body: message.body,
      icon: "/icon-192.png",
      // A notice is shown once, even if it were pushed again.
      ...(message.id === null ? {} : { tag: `notice-${String(message.id)}` }),
      data,
    },
  };
}

/** A tapped notification's data, as `notificationFor` left it (or the inbox). */
export function readTapped(data: unknown): Tapped {
  const { id, route } = fields(data);
  return { id: noticeId(id), route: appRoute(route) };
}

/** What the worker needs of an open window of the app (a `WindowClient`). */
interface AppWindow {
  focus: () => Promise<unknown>;
  postMessage: (message: OpenMessage) => void;
}

export interface TapDeps {
  /** The app's open windows. */
  windows: () => Promise<readonly AppWindow[]>;
  /** Open a new window of the app at `url`. */
  open: (url: string) => Promise<unknown>;
  /** Tell the server the notice was seen. */
  seen: (id: number) => Promise<unknown>;
}

/**
 * How long a tap waits for the notice to be marked read before it opens the app
 * anyway: the phone may have the push but no way to reach the server.
 *
 * @internal Exported for tests.
 */
export const SEEN_WAIT_MS = 2_000;

/**
 * Act on a tap: mark the notice read, then show its screen in an open window of
 * the app (the first one), or in a new one. Read first, so the screen, loading
 * as it opens, finds it read; but for `SEEN_WAIT_MS` at most.
 */
export async function onTap(tapped: Tapped, deps: TapDeps): Promise<void> {
  if (tapped.id !== null) {
    const seen = deps.seen(tapped.id).catch(() => null);
    await Promise.race([seen, new Promise((resolve) => setTimeout(resolve, SEEN_WAIT_MS))]);
  }
  const [window] = await deps.windows();
  if (window === undefined) {
    await deps.open(`/${tapped.route}`);
  } else {
    const message: OpenMessage = { type: "open", route: tapped.route };
    window.postMessage(message);
    await window.focus();
  }
}
