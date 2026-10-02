/**
 * Web Push on this phone: whether it can be on, and turning it on and off.
 *
 * Subscribing needs the service worker (production builds only), the browser's
 * permission, and the server's VAPID public key. On an iPhone, only the app
 * opened from the Home Screen can receive pushes.
 */
import { z } from "zod";

export type PushState =
  { kind: "unsupported" } | { kind: "blocked" } | { kind: "off" } | { kind: "on" };

export type PushChange = { kind: "ok"; state: PushState } | { kind: "error"; message: string };

/** @internal Exported for tests. */
export const NOT_ALLOWED = "Notifications were not allowed.";
/** @internal Exported for tests. */
export const NO_CONNECTION = "Turning notifications on needs a connection.";
/** @internal Exported for tests. */
export const NOT_SET_UP = "Notifications are not set up on the server yet.";
/** @internal Exported for tests. */
export const NOT_SUBSCRIBED = "This phone would not subscribe to notifications. Try again.";
/** @internal Exported for tests. */
export const NOT_SAVED = "The server did not save this phone's subscription. Try again.";

const SUBSCRIPTION = "/api/push/subscription";
const keySchema = z.object({ key: z.string() });
const subscriptionSchema = z.object({
  endpoint: z.string(),
  keys: z.object({ p256dh: z.string(), auth: z.string() }),
});

function supported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

/**
 * The server's VAPID public key (base64url) as the bytes `subscribe` takes.
 *
 * @internal Exported for tests.
 */
export function keyBytes(key: string): Uint8Array<ArrayBuffer> {
  const base64 = key.replaceAll("-", "+").replaceAll("_", "/");
  const binary = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="));
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

/**
 * Bytes as unpadded base64url, the form the server compares keys in.
 *
 * @internal Exported for tests.
 */
export function base64url(bytes: ArrayBuffer): string {
  const binary = String.fromCharCode(...new Uint8Array(bytes));
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

/** The server key a subscription was made with, if the browser says. */
function serverKeyOf(subscription: PushSubscription): string | null {
  const key = subscription.options.applicationServerKey;
  return key === null ? null : base64url(key);
}

/** What the server made of a subscription: kept, made with an old key, or not taken. */
type Saved = "saved" | "stale" | "failed";

/** Tell the server where to push to this phone, and with which server key. */
async function save(subscription: PushSubscription): Promise<Saved> {
  const body = subscriptionSchema.safeParse(subscription.toJSON());
  const serverKey = serverKeyOf(subscription);
  if (!body.success || serverKey === null) {
    return "failed";
  }
  try {
    const response = await fetch(SUBSCRIPTION, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body.data, server_key: serverKey }),
    });
    // 409: made with a server key since replaced; pushes to it would be refused.
    return response.ok ? "saved" : response.status === 409 ? "stale" : "failed";
  } catch {
    return "failed";
  }
}

/**
 * Whether this phone gets notifications. If it is subscribed, the server is told
 * again (it is idempotent), so a server restored from a backup catches up. A
 * subscription made with a server key since replaced is dropped: it is off.
 */
export async function pushState(): Promise<PushState> {
  if (!supported()) {
    return { kind: "unsupported" };
  }
  if (Notification.permission === "denied") {
    return { kind: "blocked" };
  }
  const subscription = await currentSubscription();
  if (subscription === null) {
    return { kind: "off" };
  }
  if ((await save(subscription)) === "stale") {
    await subscription.unsubscribe().catch(() => false);
    return { kind: "off" };
  }
  return { kind: "on" };
}

type Key = { kind: "key"; key: string } | { kind: "error"; message: string };

async function serverKey(): Promise<Key> {
  let response: Response;
  try {
    response = await fetch("/api/push/key", { cache: "no-store" });
  } catch {
    return { kind: "error", message: NO_CONNECTION };
  }
  const body = keySchema.safeParse(await response.json().catch(() => null));
  if (response.ok && body.success) {
    return { kind: "key", key: body.data.key };
  }
  return { kind: "error", message: response.status === 503 ? NOT_SET_UP : NO_CONNECTION };
}

/** Ask for permission, subscribe with the server's key, and tell the server. */
export async function turnOn(): Promise<PushChange> {
  const permission = await Notification.requestPermission();
  if (permission === "denied") {
    return { kind: "ok", state: { kind: "blocked" } };
  }
  if (permission !== "granted") {
    return { kind: "error", message: NOT_ALLOWED };
  }
  const key = await serverKey();
  if (key.kind === "error") {
    return key;
  }
  const registration = await navigator.serviceWorker.ready;
  // A subscription made with another (old) key would refuse a new one.
  const existing = await registration.pushManager.getSubscription();
  if (existing !== null && serverKeyOf(existing) !== base64url(keyBytes(key.key).buffer)) {
    await existing.unsubscribe().catch(() => false);
  }
  let subscription: PushSubscription;
  try {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(key.key),
    });
  } catch {
    return { kind: "error", message: NOT_SUBSCRIBED };
  }
  if ((await save(subscription)) !== "saved") {
    await subscription.unsubscribe().catch(() => false);
    return { kind: "error", message: NOT_SAVED };
  }
  return { kind: "ok", state: { kind: "on" } };
}

/**
 * Unsubscribe this phone, and tell the server. If the server cannot be told, its
 * next push to this phone is answered "gone" and it forgets the phone then.
 */
export async function turnOff(): Promise<PushChange> {
  const subscription = await currentSubscription();
  if (subscription !== null) {
    await subscription.unsubscribe().catch(() => false);
    const query = new URLSearchParams({ endpoint: subscription.endpoint });
    await fetch(`${SUBSCRIPTION}?${query.toString()}`, { method: "DELETE" }).catch(() => undefined);
  }
  return { kind: "ok", state: { kind: "off" } };
}

/** Post a test notice, pushed to every subscribed phone; whether the server took it. */
export async function sendTest(): Promise<boolean> {
  try {
    return (await fetch("/api/push/test", { method: "POST" })).ok;
  } catch {
    return false;
  }
}
