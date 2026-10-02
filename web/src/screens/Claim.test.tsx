import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";

const REPLY = { role: "assistant", text: "12 sets.", at: "2026-10-01T13:14:31+00:00" };

/** A fetch where the coach answers only when `answer` is called; reads answer at once. */
function coachFetch(read: unknown): {
  fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
  answer: (body: unknown) => Promise<void>;
} {
  let resolve: (response: Response) => void = () => undefined;
  const pending = new Promise<Response>((done) => {
    resolve = done;
  });
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    if (input === "/api/coach/messages" && init?.method === "POST") {
      return pending;
    }
    if (init?.method === "POST") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return Promise.resolve(new Response(JSON.stringify(read), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    fetchMock,
    answer: async (body): Promise<void> => {
      await act(async () => {
        resolve(new Response(JSON.stringify(body), { status: 200 }));
        await pending;
        await new Promise((done) => setTimeout(done, 0));
      });
    },
  };
}

function seenCalls(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>): unknown[] {
  return fetchMock.mock.calls
    .filter(([input]) => typeof input === "string" && input.startsWith("/api/inbox/"))
    .map(([input, init]) => [input, init]);
}

function hidePage(): void {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
}

afterEach(() => {
  window.location.hash = "";
  Reflect.deleteProperty(document, "visibilityState");
});

async function ask(text: string): Promise<void> {
  const form = await screen.findByRole("form", { name: "Message the coach" });
  fireEvent.change(within(form).getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(within(form).getByRole("button", { name: "Send" }));
}

describe("the Coach screen claims the notice of a reply it shows", () => {
  it("while the page is visible", async () => {
    window.location.hash = "#/coach";
    const { fetchMock, answer } = coachFetch([]);
    render(<App />);
    await ask("hi");

    await answer({ ...REPLY, notice_id: 5 });

    expect(await screen.findByText("12 sets.")).toBeInTheDocument();
    expect(seenCalls(fetchMock)).toEqual([["/api/inbox/5/seen", { method: "POST" }]]);
  });

  it("not while the page is hidden: the owner is told instead", async () => {
    window.location.hash = "#/coach";
    const { fetchMock, answer } = coachFetch([]);
    render(<App />);
    await ask("hi");
    hidePage();

    await answer({ ...REPLY, notice_id: 5 });

    expect(seenCalls(fetchMock)).toEqual([]);
  });

  it("not once the owner has left the screen", async () => {
    window.location.hash = "#/coach";
    const { fetchMock, answer } = coachFetch([]);
    render(<App />);
    await ask("hi");
    await act(async () => {
      window.location.hash = "#/history";
      await new Promise((done) => setTimeout(done, 0));
    });

    await answer({ ...REPLY, notice_id: 5 });

    expect(seenCalls(fetchMock)).toEqual([]);
  });

  it("not when the server sent no notice", async () => {
    window.location.hash = "#/coach";
    const { fetchMock, answer } = coachFetch([]);
    render(<App />);
    await ask("hi");

    await answer(REPLY);

    expect(await screen.findByText("12 sets.")).toBeInTheDocument();
    expect(seenCalls(fetchMock)).toEqual([]);
  });
});

describe("the Program screen claims the notice of the reply it shows", () => {
  it("while the page is visible", async () => {
    window.location.hash = "#/program";
    const { fetchMock, answer } = coachFetch({ active: null, proposed: null, next: null });
    render(<App />);
    const region = await screen.findByRole("region", { name: "Ask the coach" });
    fireEvent.change(within(region).getByLabelText("What you want"), {
      target: { value: "3 days" },
    });
    fireEvent.click(within(region).getByRole("button", { name: "Ask" }));

    await answer({ ...REPLY, notice_id: 8 });

    expect(await screen.findByText("12 sets.")).toBeInTheDocument();
    expect(seenCalls(fetchMock)).toEqual([["/api/inbox/8/seen", { method: "POST" }]]);
  });
});
