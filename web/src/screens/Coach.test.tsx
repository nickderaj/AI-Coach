import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { BUSY_COACH, OFFLINE_COACH } from "../api";
import { routeFetch } from "../test/logging";

const MESSAGES = "/api/coach/messages";
const HISTORY = [
  { role: "user", text: "What did I bench?", at: "2026-09-30T08:00:00+00:00" },
  { role: "assistant", text: "60 kg x 8\n- then 70 kg x 6", at: "2026-09-30T08:00:09+00:00" },
];
const REPLY = { role: "assistant", text: "12 sets.", at: "2026-10-01T13:14:31+00:00" };

beforeEach(() => {
  window.location.hash = "#/coach";
});

afterEach(() => {
  window.location.hash = "";
  vi.unstubAllGlobals();
});

function conversation(): string[] {
  const list = screen.getByRole("list", { name: "Conversation" });
  return [...list.querySelectorAll("li")]
    .map((item) => item.textContent)
    .filter((text) => text !== "");
}

function composer(): { box: HTMLElement; send: HTMLElement } {
  const form = screen.getByRole("form", { name: "Message the coach" });
  return {
    box: within(form).getByLabelText("Message"),
    send: within(form).getByRole("button", { name: "Send" }),
  };
}

/** A fetch whose POST answers only when `answer` is called. */
function slowReply(): { answer: (status: number, body: unknown) => void } {
  let resolve: (response: Response) => void = () => undefined;
  const pending = new Promise<Response>((done) => {
    resolve = done;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((_input, init) =>
      init?.method === "POST"
        ? pending
        : Promise.resolve(new Response(JSON.stringify(HISTORY), { status: 200 })),
    ),
  );
  return {
    answer: (status, body): void => {
      resolve(new Response(JSON.stringify(body), { status }));
    },
  };
}

describe("Coach", () => {
  it("shows the conversation so far", async () => {
    routeFetch({ [`GET ${MESSAGES}`]: { body: HISTORY } });
    render(<App />);

    expect(screen.getByRole("heading", { level: 1, name: "Coach" })).toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("What did I bench?", { exact: false })).toBeInTheDocument();
    expect(conversation()).toEqual([
      "You: What did I bench?",
      "Coach: 60 kg x 8\n- then 70 kg x 6",
    ]);
    const bubbles = screen.getByRole("list", { name: "Conversation" }).querySelectorAll(".bubble");
    expect([...bubbles].map((bubble) => bubble.className)).toEqual([
      "bubble user",
      "bubble assistant",
    ]);
    expect(screen.queryByText(/Nothing said yet/)).not.toBeInTheDocument();
  });

  it("opens at the bottom of the page, below the composer", async () => {
    const page = document.scrollingElement ?? document.documentElement;
    // jsdom lays nothing out: give the page a height to scroll through.
    vi.spyOn(page, "scrollHeight", "get").mockReturnValue(5000);
    routeFetch({ [`GET ${MESSAGES}`]: { body: HISTORY } });
    render(<App />);

    await screen.findByText("What did I bench?", { exact: false });
    expect(page.scrollTop).toBe(5000);
  });

  it("suggests a first question when nothing has been said", async () => {
    routeFetch({ [`GET ${MESSAGES}`]: { body: [] } });
    render(<App />);

    expect(
      await screen.findByText("Nothing said yet. Try “How did my last workout go?”"),
    ).toBeInTheDocument();
    expect(composer().send).toBeDisabled();
  });

  it.each([
    [{ status: 503, body: { detail: "the coach is not set up" } }, "The coach is not set up."],
    [{ status: 500, body: {} }, "The server answered 500"],
    [{ status: 200, body: [{ role: "system", text: "x", at: "" }] }, "The server answered 200"],
    [new TypeError("offline"), OFFLINE_COACH],
  ])("says why the conversation could not load", async (reply, message) => {
    routeFetch({ [`GET ${MESSAGES}`]: reply });
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("sends a message, shows it at once, then the reply", async () => {
    const { answer } = slowReply();
    render(<App />);
    await screen.findByText("What did I bench?", { exact: false });
    const { box, send } = composer();

    fireEvent.change(box, { target: { value: "  How many sets?  " } });
    fireEvent.click(send);

    expect(conversation().slice(2)).toEqual(["You: How many sets?", "Thinking…"]);
    expect(screen.getByRole("status")).toHaveTextContent("Thinking…");
    expect(box).toHaveValue("");
    expect(send).toBeDisabled();
    await act(async () => {
      answer(200, REPLY);
      await Promise.resolve();
    });
    expect(await screen.findByText("12 sets.")).toBeInTheDocument();
    expect(conversation().slice(2)).toEqual(["You: How many sets?", "Coach: 12 sets."]);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    const [, init] = vi.mocked(fetch).mock.calls.find(([, i]) => i?.method === "POST") ?? [];
    expect(init?.body).toBe(JSON.stringify({ text: "How many sets?" }));
    expect(init?.headers).toEqual({
      "Content-Type": "application/json",
      Accept: "application/json",
    });
  });

  it.each([
    [{ status: 409, body: { detail: "the coach is still answering" } }, BUSY_COACH],
    [
      { status: 503, body: { detail: "the coach is unavailable; try again soon" } },
      "The coach is unavailable; try again soon.",
    ],
    [{ status: 503, body: { nope: 1 } }, "The server answered 503"],
    [{ status: 422, body: {} }, "The server answered 422"],
    [new TypeError("offline"), OFFLINE_COACH],
  ])("gives the message back when it could not be sent", async (reply, message) => {
    routeFetch({ [`GET ${MESSAGES}`]: { body: [] }, [`POST ${MESSAGES}`]: reply });
    render(<App />);
    await screen.findByText(/Nothing said yet/);
    const { box, send } = composer();

    fireEvent.change(box, { target: { value: "Plan my week" } });
    fireEvent.click(send);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(box).toHaveValue("Plan my week");
    expect(conversation()).toEqual([]);
    expect(send).toBeEnabled();
  });

  it("keeps a new draft typed while a failing message was on its way", async () => {
    let fail: (error: Error) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((_input, init) =>
        init?.method === "POST"
          ? new Promise<Response>((_resolve, reject) => {
              fail = reject;
            })
          : Promise.resolve(new Response("[]", { status: 200 })),
      ),
    );
    render(<App />);
    await screen.findByText(/Nothing said yet/);
    const { box, send } = composer();
    fireEvent.change(box, { target: { value: "first" } });
    fireEvent.click(send);

    fireEvent.change(box, { target: { value: "second, typed while waiting" } });
    await act(async () => {
      fail(new TypeError("offline"));
      await Promise.resolve();
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(OFFLINE_COACH);
    expect(within(alert).getByText("Not sent: “first”")).toBeInTheDocument();
    expect(box).toHaveValue("second, typed while waiting");
    expect(conversation()).toEqual([]);
  });

  it("does not repeat the message that went back into the box", async () => {
    routeFetch({
      [`GET ${MESSAGES}`]: { body: [] },
      [`POST ${MESSAGES}`]: new TypeError("offline"),
    });
    render(<App />);
    await screen.findByText(/Nothing said yet/);
    const { box, send } = composer();
    fireEvent.change(box, { target: { value: "only once" } });
    fireEvent.click(send);
    fireEvent.change(box, { target: { value: "   " } }); // only spaces: not a new message

    const alert = await screen.findByRole("alert");
    expect(box).toHaveValue("only once");
    expect(within(alert).queryByText(/Not sent/)).not.toBeInTheDocument();

    fireEvent.change(box, { target: { value: "only once, edited" } });
    expect(within(alert).getByText("Not sent: “only once”")).toBeInTheDocument();
  });

  it("clears the last failure when sending again", async () => {
    routeFetch({
      [`GET ${MESSAGES}`]: { body: [] },
      [`POST ${MESSAGES}`]: new TypeError("offline"),
    });
    render(<App />);
    await screen.findByText(/Nothing said yet/);
    const { box, send } = composer();
    fireEvent.change(box, { target: { value: "hi" } });
    fireEvent.click(send);
    await screen.findByRole("alert");

    routeFetch({ [`GET ${MESSAGES}`]: { body: [] }, [`POST ${MESSAGES}`]: { body: REPLY } });
    fireEvent.click(send);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(await screen.findByText("12 sets.")).toBeInTheDocument();
  });

  it("sends nothing blank, and only one message at a time", async () => {
    const { answer } = slowReply();
    render(<App />);
    await screen.findByText("What did I bench?", { exact: false });
    const form = screen.getByRole("form", { name: "Message the coach" });
    const { box } = composer();

    fireEvent.change(box, { target: { value: "   " } });
    fireEvent.submit(form);
    fireEvent.change(box, { target: { value: "one" } });
    fireEvent.submit(form);
    fireEvent.change(box, { target: { value: "two" } });
    fireEvent.submit(form); // still waiting for the first

    const posts = (): number =>
      vi.mocked(fetch).mock.calls.filter(([, i]) => i?.method === "POST").length;
    expect(posts()).toBe(1);
    await act(async () => {
      answer(200, REPLY);
      await Promise.resolve();
    });
    expect(await screen.findByText("12 sets.")).toBeInTheDocument();
    expect(posts()).toBe(1);
    expect(box).toHaveValue("two");
    expect(box).toHaveAttribute("maxlength", "4000");
  });

  it("stops waiting for the history when the tab is left", async () => {
    const fetchMock = routeFetch({ [`GET ${MESSAGES}`]: { body: HISTORY } });
    const view = render(<App />);

    view.unmount();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.signal?.aborted).toBe(true);
  });
});
