// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import type { OpenMessage } from "./message";
import { routeToOpen } from "./message";
import type { TapDeps } from "./notify";
import { SEEN_WAIT_MS, notificationFor, onTap, readPush, readTapped } from "./notify";

const FALLBACK = { id: null, title: "Trainer", body: "", route: "#/inbox" };

describe("readPush", () => {
  it("reads the server's notice", () => {
    const json = JSON.stringify({
      id: 7,
      title: "Your coach answered",
      body: "Rest.",
      route: "#/coach",
    });

    expect(readPush(json)).toEqual({
      id: 7,
      title: "Your coach answered",
      body: "Rest.",
      route: "#/coach",
    });
  });

  it.each([null, "", "not json", "null", "3", '"text"', "[]"])(
    "turns %j into a plain notice opening the inbox",
    (json) => {
      expect(readPush(json)).toEqual(FALLBACK);
    },
  );

  it("fills in what is missing or wrong, field by field", () => {
    expect(readPush(JSON.stringify({ id: 1.5, title: "", body: 3, route: "#/x" }))).toEqual({
      id: null,
      title: "Trainer",
      body: "",
      route: "#/x",
    });
    expect(readPush(JSON.stringify({ id: "7", title: 7 }))).toEqual(FALLBACK);
  });

  it.each(["https://example.com/", "/#/coach", "#/Coach", "#/coach?x=1", "#coach", "javascript:x"])(
    "opens only the app's own routes, not %j",
    (route) => {
      expect(readPush(JSON.stringify({ route })).route).toBe("#/inbox");
    },
  );
});

describe("notificationFor", () => {
  it("shows the title and body, tagged by notice, and remembers what to open", () => {
    expect(notificationFor({ id: 7, title: "T", body: "B", route: "#/program" })).toEqual({
      title: "T",
      options: {
        body: "B",
        icon: "/icon-192.png",
        tag: "notice-7",
        data: { id: 7, route: "#/program" },
      },
    });
  });

  it("leaves a notice without an id untagged", () => {
    const { options } = notificationFor(FALLBACK);

    expect(options).not.toHaveProperty("tag");
    expect(options.data).toEqual({ id: null, route: "#/inbox" });
  });
});

describe("readTapped", () => {
  it("reads what notificationFor left", () => {
    expect(readTapped({ id: 7, route: "#/coach" })).toEqual({ id: 7, route: "#/coach" });
  });

  it.each([undefined, null, "x", { id: "7", route: "https://example.com/" }])(
    "opens the inbox for %j",
    (data) => {
      expect(readTapped(data)).toEqual({ id: null, route: "#/inbox" });
    },
  );
});

function deps(
  windows: { focus: () => Promise<unknown>; postMessage: (m: OpenMessage) => void }[],
): TapDeps & {
  open: ReturnType<typeof vi.fn>;
  seen: ReturnType<typeof vi.fn>;
} {
  return {
    windows: () => Promise.resolve(windows),
    open: vi.fn(() => Promise.resolve(null)),
    seen: vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))),
  };
}

describe("onTap", () => {
  it("shows the screen in the app's open window, and marks the notice read", async () => {
    const order: string[] = [];
    const window = {
      postMessage: vi.fn((message: OpenMessage) => order.push(`post ${message.route}`)),
      focus: vi.fn(() => {
        order.push("focus");
        return Promise.resolve();
      }),
    };
    const other = { postMessage: vi.fn(), focus: vi.fn(() => Promise.resolve()) };
    const tap = deps([window, other]);

    await onTap({ id: 7, route: "#/coach" }, tap);

    expect(window.postMessage).toHaveBeenCalledWith({ type: "open", route: "#/coach" });
    expect(order).toEqual(["post #/coach", "focus"]);
    expect(other.postMessage).not.toHaveBeenCalled();
    expect(tap.open).not.toHaveBeenCalled();
    expect(tap.seen).toHaveBeenCalledWith(7);
  });

  it("opens a window at the screen when none is open", async () => {
    const tap = deps([]);

    await onTap({ id: 7, route: "#/program" }, tap);

    expect(tap.open).toHaveBeenCalledWith("/#/program");
  });

  it("marks nothing read for a notice without an id", async () => {
    const tap = deps([]);

    await onTap({ id: null, route: "#/inbox" }, tap);

    expect(tap.seen).not.toHaveBeenCalled();
    expect(tap.open).toHaveBeenCalledWith("/#/inbox");
  });

  it("marks the notice read before it shows the screen", async () => {
    // So the screen, loading as it opens, already finds it read.
    const order: string[] = [];
    let finish: () => void = () => undefined;
    const tap: TapDeps = {
      windows: () => Promise.resolve([]),
      open: () => {
        order.push("open");
        return Promise.resolve(null);
      },
      seen: () =>
        new Promise((resolve) => {
          finish = (): void => {
            order.push("seen");
            resolve(null);
          };
        }),
    };

    const tapped = onTap({ id: 7, route: "#/inbox" }, tap);
    await new Promise((resolve) => setTimeout(resolve, 0));
    finish();
    await tapped;

    expect(order).toEqual(["seen", "open"]);
  });

  it("opens the screen anyway if the server does not answer in time", async () => {
    // From review: fetch has no timeout, and a phone can get a push while it
    // cannot reach the tailnet; the tap must still open the app.
    vi.useFakeTimers();
    const tap = deps([]);
    tap.seen.mockReturnValue(new Promise(() => undefined)); // never settles

    const tapped = onTap({ id: 7, route: "#/coach" }, tap);
    await vi.advanceTimersByTimeAsync(SEEN_WAIT_MS - 1);
    expect(tap.open).not.toHaveBeenCalled(); // still giving the read its chance
    await vi.advanceTimersByTimeAsync(1);
    await tapped;

    expect(tap.open).toHaveBeenCalledWith("/#/coach");
    expect(SEEN_WAIT_MS).toBe(2_000);
    vi.useRealTimers();
  });

  it("still opens the screen if the server cannot be told", async () => {
    const tap = deps([]);
    tap.seen.mockReturnValue(Promise.reject(new TypeError("offline")));

    await expect(onTap({ id: 7, route: "#/coach" }, tap)).resolves.toBeUndefined();
    expect(tap.open).toHaveBeenCalledWith("/#/coach");
  });
});

describe("routeToOpen", () => {
  it("reads the worker's message", () => {
    expect(routeToOpen({ type: "open", route: "#/coach" })).toBe("#/coach");
  });

  it.each([
    null,
    "x",
    { type: "other", route: "#/coach" },
    { type: "open", route: "/x" },
    { type: "open" },
  ])("ignores %j", (data) => {
    expect(routeToOpen(data)).toBeNull();
  });
});
