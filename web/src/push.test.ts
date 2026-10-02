import { afterEach, describe, expect, it, vi } from "vitest";

import {
  NOT_ALLOWED,
  NOT_SAVED,
  NOT_SET_UP,
  NOT_SUBSCRIBED,
  NO_CONNECTION,
  base64url,
  keyBytes,
  pushState,
  sendTest,
  turnOff,
  turnOn,
} from "./push";
import { routeFetch } from "./test/logging";
import { ENDPOINT, KEYS, SERVER_KEY, fakePush, removePush } from "./test/push";

afterEach(() => {
  removePush();
});

function body(fetchMock: ReturnType<typeof routeFetch>, call = 0): unknown {
  const init = fetchMock.mock.calls[call]?.[1];
  return JSON.parse(typeof init?.body === "string" ? init.body : "null");
}

describe("base64url", () => {
  it("encodes as the server compares keys: unpadded, URL-safe", () => {
    expect(base64url(new Uint8Array([0xfb, 0xff]).buffer)).toBe("-_8");
    expect(base64url(new Uint8Array([4]).buffer)).toBe("BA");
    expect(base64url(new Uint8Array([]).buffer)).toBe("");
  });
});

describe("keyBytes", () => {
  it("decodes the server's base64url key", () => {
    expect([...keyBytes("-_8")]).toEqual([0xfb, 0xff]);
    expect([...keyBytes("AAAX")]).toEqual([0, 0, 0x17]);
    expect([...keyBytes("BA")]).toEqual([4]);
  });
});

describe("pushState", () => {
  it("is unsupported without the browser's push APIs", async () => {
    await expect(pushState()).resolves.toEqual({ kind: "unsupported" });
  });

  it.each(["PushManager", "Notification"])("is unsupported without %s", async (missing) => {
    fakePush();
    Reflect.deleteProperty(globalThis, missing);

    await expect(pushState()).resolves.toEqual({ kind: "unsupported" });
  });

  it("is unsupported without a service worker", async () => {
    fakePush();
    removePush();

    await expect(pushState()).resolves.toEqual({ kind: "unsupported" });
  });

  it("is blocked when the owner refused notifications", async () => {
    fakePush({ permission: "denied" });

    await expect(pushState()).resolves.toEqual({ kind: "blocked" });
  });

  it("is off without a subscription", async () => {
    fakePush({ permission: "granted" });
    const fetchMock = routeFetch({});

    await expect(pushState()).resolves.toEqual({ kind: "off" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("is on with one, and tells the server again", async () => {
    fakePush({}, true);
    const fetchMock = routeFetch({ "PUT /api/push/subscription": { body: null } });

    await expect(pushState()).resolves.toEqual({ kind: "on" });
    expect(body(fetchMock)).toEqual({ endpoint: ENDPOINT, keys: KEYS, server_key: SERVER_KEY });
  });

  it("drops a subscription made with a server key since replaced", async () => {
    const push = fakePush({}, "AQ");
    routeFetch({
      "PUT /api/push/subscription": {
        status: 409,
        body: { detail: "subscribed with another server key; subscribe again" },
      },
    });

    await expect(pushState()).resolves.toEqual({ kind: "off" });
    expect(push.unsubscribe).toHaveBeenCalled();
  });

  it("is on even when the server cannot be told", async () => {
    fakePush({}, true);
    routeFetch({ "PUT /api/push/subscription": new TypeError("offline") });

    await expect(pushState()).resolves.toEqual({ kind: "on" });
  });
});

describe("turnOn", () => {
  it("asks, subscribes with the server's key and saves the subscription", async () => {
    const push = fakePush();
    const fetchMock = routeFetch({
      "GET /api/push/key": { body: { key: "BA" } },
      "PUT /api/push/subscription": { body: null },
    });

    await expect(turnOn()).resolves.toEqual({ kind: "ok", state: { kind: "on" } });

    expect(push.subscribe).toHaveBeenCalledWith({
      userVisibleOnly: true,
      applicationServerKey: new Uint8Array([4]),
    });
    expect(fetchMock.mock.calls[0]?.[1]).toEqual({ cache: "no-store" });
    const put = fetchMock.mock.calls[1]?.[1];
    expect(put?.method).toBe("PUT");
    expect(put?.headers).toEqual({ "Content-Type": "application/json" });
    expect(body(fetchMock, 1)).toEqual({ endpoint: ENDPOINT, keys: KEYS, server_key: "BA" });
  });

  it("first drops a subscription made with an old server key", async () => {
    const push = fakePush({}, "AQ");
    const fetchMock = routeFetch({
      "GET /api/push/key": { body: { key: "BA" } },
      "PUT /api/push/subscription": { body: null },
    });

    await expect(turnOn()).resolves.toEqual({ kind: "ok", state: { kind: "on" } });

    expect(push.unsubscribe).toHaveBeenCalledTimes(1);
    expect(push.subscribe).toHaveBeenCalledTimes(1);
    expect(body(fetchMock, 1)).toEqual({ endpoint: ENDPOINT, keys: KEYS, server_key: "BA" });
  });

  it("keeps a subscription made with the current key", async () => {
    const push = fakePush({}, "BA");
    routeFetch({
      "GET /api/push/key": { body: { key: "BA" } },
      "PUT /api/push/subscription": { body: null },
    });

    await expect(turnOn()).resolves.toEqual({ kind: "ok", state: { kind: "on" } });
    expect(push.unsubscribe).not.toHaveBeenCalled();
  });

  it("is blocked when the owner refuses", async () => {
    const push = fakePush({ answer: "denied" });

    await expect(turnOn()).resolves.toEqual({ kind: "ok", state: { kind: "blocked" } });
    expect(push.subscribe).not.toHaveBeenCalled();
  });

  it("stays off when the owner dismisses the question", async () => {
    fakePush({ answer: "default" });

    await expect(turnOn()).resolves.toEqual({ kind: "error", message: NOT_ALLOWED });
  });

  it.each([
    [new TypeError("offline"), NO_CONNECTION],
    [{ status: 503, body: { detail: "notifications are not set up" } }, NOT_SET_UP],
    [{ status: 500, body: {} }, NO_CONNECTION],
    [{ body: { nokey: 1 } }, NO_CONNECTION],
  ])("needs the server's key (%j)", async (reply, message) => {
    const push = fakePush();
    routeFetch({ "GET /api/push/key": reply });

    await expect(turnOn()).resolves.toEqual({ kind: "error", message });
    expect(push.subscribe).not.toHaveBeenCalled();
  });

  it("says so when the phone will not subscribe", async () => {
    const push = fakePush();
    push.subscribe.mockReturnValue(Promise.reject(new DOMException("no", "AbortError")));
    routeFetch({ "GET /api/push/key": { body: { key: "BA" } } });

    await expect(turnOn()).resolves.toEqual({ kind: "error", message: NOT_SUBSCRIBED });
  });

  it.each([[new TypeError("offline")], [{ status: 422, body: {} }]])(
    "unsubscribes again when the server does not save it (%j)",
    async (reply) => {
      const push = fakePush();
      routeFetch({
        "GET /api/push/key": { body: { key: "BA" } },
        "PUT /api/push/subscription": reply,
      });

      await expect(turnOn()).resolves.toEqual({ kind: "error", message: NOT_SAVED });
      expect(push.unsubscribe).toHaveBeenCalled();
      expect(push.subscription).toBeNull();
    },
  );

  it("refuses a subscription without keys", async () => {
    const push = fakePush();
    push.subscribe.mockImplementation(() => {
      const keyless = {
        endpoint: ENDPOINT,
        options: { applicationServerKey: new Uint8Array([4]).buffer },
        toJSON: (): unknown => ({ endpoint: ENDPOINT }),
        unsubscribe: push.unsubscribe,
      };
      push.subscription = keyless;
      return Promise.resolve(keyless);
    });
    const fetchMock = routeFetch({ "GET /api/push/key": { body: { key: "BA" } } });

    await expect(turnOn()).resolves.toEqual({ kind: "error", message: NOT_SAVED });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("turnOff", () => {
  it("unsubscribes and tells the server", async () => {
    const push = fakePush({}, true);
    const fetchMock = routeFetch({
      [`DELETE /api/push/subscription?endpoint=${encodeURIComponent(ENDPOINT)}`]: { body: null },
    });

    await expect(turnOff()).resolves.toEqual({ kind: "ok", state: { kind: "off" } });

    expect(push.unsubscribe).toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/push/subscription?endpoint=${encodeURIComponent(ENDPOINT)}`,
      { method: "DELETE" },
    );
  });

  it("is off even when the server cannot be told", async () => {
    fakePush({}, true);
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("offline"))),
    );

    await expect(turnOff()).resolves.toEqual({ kind: "ok", state: { kind: "off" } });
  });

  it("does nothing more without a subscription", async () => {
    fakePush({ permission: "granted" });
    const fetchMock = routeFetch({});

    await expect(turnOff()).resolves.toEqual({ kind: "ok", state: { kind: "off" } });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("sendTest", () => {
  it("posts a test notice", async () => {
    const fetchMock = routeFetch({ "POST /api/push/test": { status: 201, body: { id: 1 } } });

    await expect(sendTest()).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/push/test", { method: "POST" });
  });

  it.each([[new TypeError("offline")], [{ status: 500, body: {} }]])(
    "says when it could not (%j)",
    async (reply) => {
      routeFetch({ "POST /api/push/test": reply });

      await expect(sendTest()).resolves.toBe(false);
    },
  );
});

describe("a subscription without its server key", () => {
  it("is not sent: the server could not tell which key it is for", async () => {
    const push = fakePush({}, true);
    if (push.subscription !== null) {
      push.subscription = { ...push.subscription, options: { applicationServerKey: null } };
    }
    const fetchMock = routeFetch({});

    await expect(pushState()).resolves.toEqual({ kind: "on" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
