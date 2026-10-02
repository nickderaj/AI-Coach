import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { INBOX_CHANGED } from "../sw/message";
import { at } from "../test/fetch";
import { routeFetch } from "../test/logging";
import { fakePush, removePush } from "../test/push";

const COACH = {
  id: 3,
  kind: "coach",
  title: "Your coach answered",
  body: "Rest tomorrow.",
  at: "2026-10-01T21:15:00+00:00",
  read: false,
  route: "#/coach",
};
const TEST = {
  id: 1,
  kind: "test",
  title: "Notifications are on",
  body: "This is how the trainer will reach you.",
  at: "2026-10-02T14:10:03+00:00",
  read: false,
  route: "#/inbox",
};
const PROPOSAL = {
  id: 2,
  kind: "proposal",
  title: "Your coach proposed Upper/Lower",
  body: "",
  at: "2026-09-30T08:00:00+00:00",
  read: true,
  route: "#/program",
};

afterEach(() => {
  window.location.hash = "";
  removePush();
});

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("Inbox", () => {
  beforeEach(() => {
    window.location.hash = "#/inbox";
  });

  it("lists the notices, unread ones marked, newest first", async () => {
    routeFetch({ "GET /api/inbox": { body: { unread: 1, notices: [COACH, PROPOSAL] } } });

    render(<App />);

    const list = await screen.findByRole("list", { name: "Notices" });
    const items = within(list).getAllByRole("link");
    expect(items.map((item) => item.getAttribute("href"))).toEqual(["#/coach", "#/program"]);
    expect(items[0]).toHaveTextContent("Your coach answered");
    expect(items[0]).toHaveTextContent("Rest tomorrow.");
    expect(items[0]).toHaveClass("unread");
    expect(within(at(items, 0)).getByLabelText("Unread")).toBeInTheDocument();
    expect(items[1]).not.toHaveClass("unread");
    expect(within(at(items, 1)).queryByLabelText("Unread")).toBeNull();
    // Times are shown in the phone's zone (the tests run in Auckland).
    expect(items[0]).toHaveTextContent("10:15");
    expect(screen.getByText("1 unread")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "‹ Home" })).toHaveAttribute("href", "#/");
  });

  it("marks a notice read when it is opened", async () => {
    const fetchMock = routeFetch({
      "GET /api/inbox": { body: { unread: 1, notices: [COACH] } },
      "POST /api/inbox/3/seen": { body: null },
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("link", { name: /Your coach answered/ }));
    await settle(); // the link's own navigation, to the Coach tab

    expect(fetchMock).toHaveBeenCalledWith("/api/inbox/3/seen", { method: "POST" });
    expect(window.location.hash).toBe("#/coach");
  });

  it("shows a notice read once opened, even one that opens the Inbox itself", async () => {
    // From the owner: a test notice opens #/inbox, the screen already shown, so
    // nothing reloaded and it stayed unread until "Mark all read".
    let read = false;
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      if (input === "/api/inbox/1/seen" && init?.method === "POST") {
        read = true;
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      const notice = { ...TEST, read };
      const body = { unread: read ? 0 : 1, notices: [notice] };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.click(await screen.findByRole("link", { name: /Notifications are on/ }));
    await settle();

    expect(window.location.hash).toBe("#/inbox");
    expect(screen.queryByLabelText("Unread")).toBeNull();
    expect(screen.queryByText("1 unread")).toBeNull();
  });

  it("reads the inbox again when the app comes back to the front", async () => {
    let unread = 1;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify({ unread, notices: [{ ...TEST, read: unread === 0 }] }), {
            status: 200,
          }),
        ),
      ),
    );
    render(<App />);
    expect(await screen.findByText("1 unread")).toBeInTheDocument();

    unread = 0; // read elsewhere: tapped as a notification, say
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.queryByText("1 unread")).toBeNull();
  });

  it("reads the inbox again when a tapped notification opens it", async () => {
    let unread = 1;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify({ unread, notices: [{ ...TEST, read: unread === 0 }] }), {
            status: 200,
          }),
        ),
      ),
    );
    render(<App />);
    expect(await screen.findByText("1 unread")).toBeInTheDocument();

    unread = 0;
    await act(async () => {
      window.dispatchEvent(new Event(INBOX_CHANGED));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.queryByText("1 unread")).toBeNull();
  });

  it("marks everything read, then reads the inbox again", async () => {
    const fetchMock = routeFetch({
      "GET /api/inbox": { body: { unread: 1, notices: [COACH] } },
      "POST /api/inbox/read": { body: null },
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Mark all read" }));
    await settle();

    expect(fetchMock).toHaveBeenCalledWith("/api/inbox/read", { method: "POST" });
    const reads = fetchMock.mock.calls.filter(
      ([path, init]) => path === "/api/inbox" && init?.method === undefined,
    );
    expect(reads).toHaveLength(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([[new TypeError("offline")], [{ status: 500, body: {} }]])(
    "says when marking everything read failed (%j)",
    async (reply) => {
      routeFetch({
        "GET /api/inbox": { body: { unread: 1, notices: [COACH] } },
        "POST /api/inbox/read": reply,
      });
      render(<App />);

      fireEvent.click(await screen.findByRole("button", { name: "Mark all read" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Could not reach the server. Try again.",
      );
    },
  );

  it("offers nothing to mark when all are read", async () => {
    routeFetch({ "GET /api/inbox": { body: { unread: 0, notices: [PROPOSAL] } } });
    render(<App />);

    await screen.findByRole("list", { name: "Notices" });

    expect(screen.queryByRole("button", { name: "Mark all read" })).toBeNull();
    expect(screen.queryByText(/unread/)).toBeNull();
  });

  it("says what lands here while it is empty", async () => {
    routeFetch({ "GET /api/inbox": { body: { unread: 0, notices: [] } } });
    render(<App />);

    expect(await screen.findByText(/Nothing yet\./)).toBeInTheDocument();
  });

  it("refuses a notice that would open somewhere else", async () => {
    const elsewhere = { ...COACH, route: "https://example.com/" };
    routeFetch({ "GET /api/inbox": { body: { unread: 1, notices: [elsewhere] } } });
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server sent data this app does not understand",
    );
  });

  it("belongs to Home in the tabs", async () => {
    routeFetch({ "GET /api/inbox": { body: { unread: 0, notices: [] } } });
    render(<App />);
    await settle();

    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
  });
});

describe("Home's inbox link", () => {
  beforeEach(() => {
    window.location.hash = "#/";
  });

  it("shows how many notices are unread", async () => {
    routeFetch({
      "GET /api/inbox": { body: { unread: 2, notices: [COACH, PROPOSAL] } },
      "GET /api/workouts?limit=500": { body: [] },
    });
    render(<App />);

    const link = await screen.findByRole("link", { name: "Inbox, 2 unread" });
    expect(link).toHaveAttribute("href", "#/inbox");
    expect(link).toHaveTextContent("2");
  });

  it.each([[{ body: { unread: 0, notices: [] } }], [{ status: 500, body: {} }]])(
    "is a plain link without unread notices (%j)",
    async (reply) => {
      routeFetch({ "GET /api/inbox": reply, "GET /api/workouts?limit=500": { body: [] } });
      render(<App />);
      await settle();

      const link = screen.getByRole("link", { name: "Inbox" });
      expect(link).toHaveTextContent(/^✉$/);
    },
  );
});

describe("Settings: notifications", () => {
  beforeEach(() => {
    window.location.hash = "#/settings";
  });

  function card(): HTMLElement {
    return screen.getByRole("region", { name: "Notifications" });
  }

  it("says when this browser cannot have them", async () => {
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: null } } });
    render(<App />);

    expect(await within(card()).findByText(/add the app to your Home Screen/)).toBeInTheDocument();
    expect(within(card()).queryByRole("switch")).toBeNull();
  });

  it("says when they are blocked", async () => {
    fakePush({ permission: "denied" });
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: null } } });
    render(<App />);

    expect(await within(card()).findByText(/blocked for this app/)).toBeInTheDocument();
  });

  it("checks first", () => {
    fakePush();
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: null } } });
    render(<App />);

    expect(within(card()).getByText("Checking…")).toBeInTheDocument();
  });

  it("turns them on, then sends a test", async () => {
    const push = fakePush();
    const fetchMock = routeFetch({
      "GET /api/profile": { body: { bodyweight_kg: null } },
      "GET /api/push/key": { body: { key: "BA" } },
      "PUT /api/push/subscription": { body: null },
      "POST /api/push/test": { status: 201, body: { id: 9 } },
    });
    render(<App />);

    const toggle = await within(card()).findByRole("switch", { name: "Notify me on this phone" });
    expect(toggle).not.toBeChecked();
    expect(within(card()).queryByRole("button", { name: "Send a test notification" })).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toBeDisabled();
    await settle();

    expect(toggle).toBeChecked();
    expect(toggle).toBeEnabled();
    expect(push.subscribe).toHaveBeenCalled();

    fireEvent.click(within(card()).getByRole("button", { name: "Send a test notification" }));
    expect(await within(card()).findByRole("status")).toHaveTextContent(
      "Sent. It should arrive in a moment, and it’s in the Inbox.",
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/push/test", { method: "POST" });
  });

  it("says why turning them on failed, and stays off", async () => {
    fakePush();
    routeFetch({
      "GET /api/profile": { body: { bodyweight_kg: null } },
      "GET /api/push/key": { status: 503, body: { detail: "notifications are not set up" } },
    });
    render(<App />);

    fireEvent.click(await within(card()).findByRole("switch"));

    expect(await within(card()).findByRole("alert")).toHaveTextContent(
      "Notifications are not set up on the server yet.",
    );
    expect(within(card()).getByRole("switch")).not.toBeChecked();
  });

  it("turns them off", async () => {
    const push = fakePush({}, true);
    routeFetch({
      "GET /api/profile": { body: { bodyweight_kg: null } },
      "PUT /api/push/subscription": { body: null },
      [`DELETE /api/push/subscription?endpoint=${encodeURIComponent("https://web.push.apple.com/QGuT8ar")}`]:
        { body: null },
    });
    render(<App />);

    const toggle = await within(card()).findByRole("switch");
    await settle();
    expect(toggle).toBeChecked();

    fireEvent.click(toggle);
    await settle();

    expect(toggle).not.toBeChecked();
    expect(push.subscription).toBeNull();
  });

  it("says when the test could not be sent", async () => {
    fakePush({}, true);
    routeFetch({
      "GET /api/profile": { body: { bodyweight_kg: null } },
      "PUT /api/push/subscription": { body: null },
      "POST /api/push/test": new TypeError("offline"),
    });
    render(<App />);

    fireEvent.click(
      await within(card()).findByRole("button", { name: "Send a test notification" }),
    );

    expect(await within(card()).findByRole("alert")).toHaveTextContent(
      "Could not reach the server. Try again.",
    );
  });

  it("does not update after leaving the screen", async () => {
    fakePush();
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: null } } });
    const error = vi.spyOn(console, "error");
    const { unmount } = render(<App />);

    unmount();
    await settle();

    expect(error).not.toHaveBeenCalled();
  });
});
