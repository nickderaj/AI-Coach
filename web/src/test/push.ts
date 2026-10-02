import { vi } from "vitest";

export const ENDPOINT = "https://web.push.apple.com/QGuT8ar";
export const KEYS = { p256dh: "BKey", auth: "secret" };
/** The server key the fake browser subscribed with: base64url of [4]. */
export const SERVER_KEY = "BA";

interface Subscription {
  endpoint: string;
  options: { applicationServerKey: ArrayBuffer | null };
  toJSON: () => unknown;
  unsubscribe: () => Promise<boolean>;
}

function bytes(base64url: string): ArrayBuffer {
  const binary = atob(base64url.replaceAll("-", "+").replaceAll("_", "/").padEnd(4, "="));
  return Uint8Array.from(binary, (char) => char.charCodeAt(0)).buffer;
}

export interface FakePush {
  permission: NotificationPermission;
  /** What requestPermission answers. */
  answer: NotificationPermission;
  subscription: Subscription | null;
  subscribe: ReturnType<
    typeof vi.fn<
      (options: { applicationServerKey: Uint8Array<ArrayBuffer> }) => Promise<Subscription>
    >
  >;
  unsubscribe: ReturnType<typeof vi.fn<() => Promise<boolean>>>;
}

/**
 * Install a browser that can push: a service worker, a push manager and
 * permissions. `subscribed` starts with the browser already subscribed.
 */
export function fakePush(
  start: { permission?: NotificationPermission; answer?: NotificationPermission } = {},
  subscribed: boolean | string = false,
): FakePush {
  const unsubscribe = vi.fn((): Promise<boolean> => {
    state.subscription = null;
    return Promise.resolve(true);
  });
  const made = (serverKey: ArrayBuffer | null): Subscription => ({
    endpoint: ENDPOINT,
    options: { applicationServerKey: serverKey },
    toJSON: () => ({ endpoint: ENDPOINT, expirationTime: null, keys: KEYS }),
    unsubscribe,
  });
  const startKey = typeof subscribed === "string" ? subscribed : SERVER_KEY;
  const state: FakePush = {
    permission: start.permission ?? (subscribed === false ? "default" : "granted"),
    answer: start.answer ?? "granted",
    subscription: subscribed === false ? null : made(bytes(startKey)),
    subscribe: vi.fn(
      (options: { applicationServerKey: Uint8Array<ArrayBuffer> }): Promise<Subscription> => {
        state.subscription = made(options.applicationServerKey.buffer);
        return Promise.resolve(state.subscription);
      },
    ),
    unsubscribe,
  };
  const registration = {
    pushManager: {
      getSubscription: (): Promise<Subscription | null> => Promise.resolve(state.subscription),
      subscribe: state.subscribe,
    },
  };
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { ready: Promise.resolve(registration) },
  });
  // Only its presence is checked.
  vi.stubGlobal("PushManager", function PushManager(): void {
    // Never constructed.
  });
  vi.stubGlobal("Notification", {
    get permission(): NotificationPermission {
      return state.permission;
    },
    requestPermission: (): Promise<NotificationPermission> => {
      state.permission = state.answer;
      return Promise.resolve(state.answer);
    },
  });
  return state;
}

/** Take the service worker away again (the globals are unstubbed by vitest). */
export function removePush(): void {
  Reflect.deleteProperty(navigator, "serviceWorker");
}
