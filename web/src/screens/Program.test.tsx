import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { OFFLINE_PROGRAM } from "../api";
import { routeFetch } from "../test/logging";
import { blockLetter, formatPrescription, programRequest } from "./Program";

const PROGRAMS = "/api/programs";

function exercise(
  id: number,
  name: string,
  extra: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    id,
    exercise_id: id + 100,
    name,
    equipment: "barbell",
    measure: "reps",
    sets: 3,
    rep_min: 8,
    rep_max: 12,
    start_load_kg: null,
    notes: null,
    ...extra,
  };
}

function program(
  id: number,
  name: string,
  status: string,
  extra: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    id,
    name,
    notes: null,
    training_weeks: 6,
    status,
    started_at: status === "active" ? "2026-09-28T07:00:00+00:00" : null,
    days: [
      {
        id: id * 10 + 1,
        name: "Upper",
        blocks: [
          { rest_s: 120, exercises: [exercise(1, "Bench Press", { start_load_kg: 60 })] },
          {
            rest_s: 60,
            exercises: [exercise(2, "Cable Row"), exercise(3, "Curl", { rep_min: 10 })],
          },
        ],
      },
      {
        id: id * 10 + 2,
        name: "Lower",
        blocks: [
          {
            rest_s: 90,
            exercises: [
              exercise(4, "Dead Hang", { measure: "seconds", sets: 2, rep_min: 30, rep_max: 45 }),
            ],
          },
        ],
      },
    ],
    ...extra,
  };
}

const ACTIVE = program(1, "Upper/Lower", "active", { notes: "Two days a week." });
const PROPOSED = program(2, "Full Body", "proposed", { notes: "More legs." });

beforeEach(() => {
  window.location.hash = "#/program";
});

afterEach(() => {
  window.location.hash = "";
  vi.unstubAllGlobals();
});

function programsReply(
  active: unknown,
  proposed: unknown,
  next: unknown,
): Record<string, { body: unknown }> {
  return { [`GET ${PROGRAMS}`]: { body: { active, proposed, next } } };
}

describe("formatting", () => {
  it("letters blocks", () => {
    expect([0, 1, 25].map(blockLetter)).toEqual(["A", "B", "Z"]);
  });

  it("writes a prescription", () => {
    const base = { sets: 3, rep_min: 8, rep_max: 12, measure: "reps" };
    expect(formatPrescription(base)).toBe("3 × 8–12");
    expect(formatPrescription({ ...base, rep_min: 5, rep_max: 5 })).toBe("3 × 5");
    expect(
      formatPrescription({ ...base, sets: 2, rep_min: 30, rep_max: 45, measure: "seconds" }),
    ).toBe("2 × 30–45 s");
  });

  it("frames a request for the coach", () => {
    expect(programRequest("4 days", false)).toBe("Plan a program for me: 4 days");
    expect(programRequest("more legs", true)).toBe("Change my program: more legs");
  });
});

describe("Program", () => {
  it("has its own tab", async () => {
    routeFetch(programsReply(null, null, null));
    render(<App />);

    const tab = screen.getByRole("link", { name: "Program" });
    expect(tab).toHaveAttribute("aria-current", "page");
    expect(tab).toHaveAttribute("href", "#/program");
    expect(screen.getByRole("heading", { level: 1, name: "Program" })).toBeInTheDocument();
    expect(await screen.findByText("No program yet.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Plan one with the coach" })).toBeInTheDocument();
  });

  it("shows the block, the week and the next day", async () => {
    routeFetch(programsReply(ACTIVE, null, { week: 3, day: 2 }));
    render(<App />);

    const current = await screen.findByRole("region", { name: "Current program" });
    expect(within(current).getByRole("heading", { name: "Upper/Lower" })).toBeInTheDocument();
    expect(within(current).getByText("Started Mon 28 Sept")).toBeInTheDocument();
    expect(within(current).getByText("Week 3 of 6. Next: Lower.")).toBeInTheDocument();
    expect(within(current).getByText("Two days a week.")).toBeInTheDocument();
    const weeks = within(current)
      .getAllByRole("listitem")
      .filter((item) => item.closest(".weeks"));
    expect(weeks.map((week) => week.textContent)).toEqual(["1", "2", "3", "4", "5", "6", "D"]);
    expect(weeks.map((week) => week.className)).toEqual(["done", "done", "", "", "", "", ""]);
    expect(weeks[2]).toHaveAttribute("aria-current", "step");
    expect(weeks[6]).toHaveAttribute("title", "Deload week");
    expect(weeks[0]).toHaveAttribute("title", "Week 1");

    const days = current.querySelectorAll(".program-day");
    expect([...days].map((day) => day.getAttribute("aria-current"))).toEqual([null, "step"]);
    expect(within(days[1] as HTMLElement).getByText("Next")).toBeInTheDocument();
    const upper = days[0] as HTMLElement;
    expect([...upper.querySelectorAll(".lines li")].map((line) => line.textContent)).toEqual([
      "A Bench Press3 × 8–12",
      "B1 Cable Row3 × 8–12",
      "B2 Curl3 × 10–12",
    ]);
    expect(within(upper).getByText("Superset")).toBeInTheDocument();
    // Not "rest": that class is the rest timer's floating bar.
    expect(within(upper).getByText("Rest 120 s")).toHaveClass("block-rest");
    expect(within(upper).getByText("Rest 120 s")).not.toHaveClass("rest");
    expect(within(days[1] as HTMLElement).getByText("2 × 30–45 s")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Change it with the coach" })).toBeInTheDocument();
  });

  it("opens Today from the next day only", async () => {
    routeFetch(programsReply(ACTIVE, null, { week: 3, day: 2 }));
    render(<App />);

    const current = await screen.findByRole("region", { name: "Current program" });
    const days = current.querySelectorAll(".program-day");
    const link = within(days[1] as HTMLElement).getByRole("link", { name: "Lower" });
    expect(link).toHaveAttribute("href", "#/today");
    expect(within(days[0] as HTMLElement).queryByRole("link")).not.toBeInTheDocument();
  });

  it("links no day of a proposal", async () => {
    routeFetch(programsReply(null, PROPOSED, null));
    render(<App />);

    const proposal = await screen.findByRole("region", { name: "Proposed program" });
    expect(proposal.querySelector(".day-link")).toBeNull();
  });

  it("marks the deload week", async () => {
    routeFetch(programsReply(ACTIVE, null, { week: 7, day: 1 }));
    render(<App />);

    const line = await screen.findByText(
      "Deload week: the same days, fewer sets and lighter. Next: Upper.",
    );
    expect(line).toHaveClass("deload");
    const weeks = document.querySelectorAll(".weeks li");
    expect(weeks[6]).toHaveAttribute("aria-current", "step");
  });

  it("says when the block is done", async () => {
    routeFetch(programsReply({ ...ACTIVE, started_at: null }, null, null));
    render(<App />);

    const line = await screen.findByText("Block complete. Ask the coach for your next program.");
    expect(line).not.toHaveClass("deload");
    expect(screen.queryByText(/Started/)).not.toBeInTheDocument();
    expect(
      [...document.querySelectorAll(".weeks li")].every((week) => week.className === "done"),
    ).toBe(true);
    expect(screen.queryByText("Next")).not.toBeInTheDocument();
  });

  it("starts a proposal at once when there is no program", async () => {
    const fetchMock = routeFetch({
      ...programsReply(null, PROPOSED, null),
      "POST /api/programs/2/accept": { body: PROPOSED },
    });
    render(<App />);

    const proposal = await screen.findByRole("region", { name: "Proposed program" });
    expect(within(proposal).getByText("Proposed by your coach")).toBeInTheDocument();
    expect(within(proposal).getByText("More legs.")).toBeInTheDocument();
    expect(within(proposal).getByText("3 × 8–12 · 60 kg")).toBeInTheDocument();
    expect(within(proposal).queryByText(/replaces/)).not.toBeInTheDocument();
    expect(screen.getByText("No program yet.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Change it with the coach" })).toBeInTheDocument();
    fireEvent.click(within(proposal).getByRole("button", { name: "Start this program" }));

    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.filter(([path]) => path === PROGRAMS)).toHaveLength(2);
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/programs/2/accept", {
      method: "POST",
      headers: { Accept: "application/json" },
    });
  });

  it("asks before a proposal replaces the program", async () => {
    const fetchMock = routeFetch({
      ...programsReply(ACTIVE, PROPOSED, { week: 2, day: 1 }),
      "POST /api/programs/2/accept": { body: PROPOSED },
    });
    render(<App />);

    const proposal = await screen.findByRole("region", { name: "Proposed program" });
    fireEvent.click(within(proposal).getByRole("button", { name: "Start this program" }));
    const ask = within(proposal).getByRole("group", { name: "Replace" });
    expect(ask).toHaveTextContent("Start “Full Body”? It replaces “Upper/Lower”.");
    fireEvent.click(within(ask).getByRole("button", { name: "Keep my program" }));
    expect(within(proposal).queryByRole("group")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([path]) => path === "/api/programs/2/accept")).toBe(false);

    fireEvent.click(within(proposal).getByRole("button", { name: "Start this program" }));
    fireEvent.click(within(proposal).getByRole("button", { name: "Yes, start it" }));

    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.some(([path]) => path === "/api/programs/2/accept")).toBe(true);
    });
  });

  it("turns a proposal down after asking", async () => {
    const fetchMock = routeFetch({
      ...programsReply(null, PROPOSED, null),
      "POST /api/programs/2/decline": { body: null },
    });
    render(<App />);

    const proposal = await screen.findByRole("region", { name: "Proposed program" });
    fireEvent.click(within(proposal).getByRole("button", { name: "Turn down" }));
    const ask = within(proposal).getByRole("group", { name: "Turn down" });
    fireEvent.click(within(ask).getByRole("button", { name: "Keep it" }));
    expect(within(proposal).queryByRole("group")).not.toBeInTheDocument();

    fireEvent.click(within(proposal).getByRole("button", { name: "Turn down" }));
    fireEvent.click(within(proposal).getByRole("button", { name: "Yes, turn it down" }));

    await vi.waitFor(() => {
      // The proposal on screen, by its id: never whichever came after it.
      expect(fetchMock).toHaveBeenCalledWith("/api/programs/2/decline", {
        method: "POST",
        headers: { Accept: "application/json" },
      });
    });
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.filter(([path]) => path === PROGRAMS)).toHaveLength(2);
    });
  });

  it.each([
    [
      { status: 409, body: { detail: "program 2 is not the proposal" } },
      "Program 2 is not the proposal.",
    ],
    [{ status: 500, body: "oops" }, "The server answered 500"],
    [new TypeError("offline"), OFFLINE_PROGRAM],
    [
      { status: 409, body: { detail: "finish or discard the workout in progress first" } },
      "Finish or discard the workout in progress first.",
    ],
  ])("says why a change failed", async (reply, message) => {
    routeFetch({ ...programsReply(null, PROPOSED, null), "POST /api/programs/2/accept": reply });
    render(<App />);

    const proposal = await screen.findByRole("region", { name: "Proposed program" });
    fireEvent.click(within(proposal).getByRole("button", { name: "Start this program" }));

    expect(await within(proposal).findByRole("alert")).toHaveTextContent(message);
    expect(within(proposal).getByRole("button", { name: "Start this program" })).toBeEnabled();
  });

  it("says why turning down failed, and offers it again", async () => {
    routeFetch({
      ...programsReply(null, PROPOSED, null),
      "POST /api/programs/2/decline": new TypeError("offline"),
    });
    render(<App />);

    const proposal = await screen.findByRole("region", { name: "Proposed program" });
    fireEvent.click(within(proposal).getByRole("button", { name: "Turn down" }));
    fireEvent.click(within(proposal).getByRole("button", { name: "Yes, turn it down" }));

    expect(await within(proposal).findByRole("alert")).toHaveTextContent(OFFLINE_PROGRAM);
    expect(within(proposal).getByRole("button", { name: "Turn down" })).toBeInTheDocument();
  });

  it("locks every proposal button while a change is on its way", async () => {
    let answer: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((done) => {
      answer = done;
    });
    const fetchMock = vi.fn<typeof fetch>((_input, init) =>
      init?.method === "POST"
        ? pending
        : Promise.resolve(
            new Response(JSON.stringify({ active: null, proposed: PROPOSED, next: null })),
          ),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const proposal = await screen.findByRole("region", { name: "Proposed program" });
    const start = within(proposal).getByRole("button", { name: "Start this program" });
    fireEvent.click(start);
    const turnDown = within(proposal).getByRole("button", { name: "Turn down" });

    expect(start).toBeDisabled();
    expect(turnDown).toBeDisabled();
    fireEvent.click(turnDown);
    fireEvent.click(start);
    expect(within(proposal).queryByRole("group")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    await act(async () => {
      answer(
        new Response(JSON.stringify({ detail: "program 2 is not the proposal" }), { status: 409 }),
      );
      await pending;
    });
    expect(await within(proposal).findByRole("alert")).toHaveTextContent(
      "Program 2 is not the proposal.",
    );
    expect(within(proposal).getByRole("button", { name: "Turn down" })).toBeEnabled();
  });

  it("locks the confirmation too while it is on its way", async () => {
    let answer: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((done) => {
      answer = done;
    });
    const fetchMock = vi.fn<typeof fetch>((_input, init) =>
      init?.method === "POST"
        ? pending
        : Promise.resolve(
            new Response(JSON.stringify({ active: ACTIVE, proposed: PROPOSED, next: null })),
          ),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const proposal = await screen.findByRole("region", { name: "Proposed program" });
    fireEvent.click(within(proposal).getByRole("button", { name: "Start this program" }));
    const yes = within(proposal).getByRole("button", { name: "Yes, start it" });
    fireEvent.click(yes);
    const keep = within(proposal).getByRole("button", { name: "Keep my program" });

    expect([yes, keep].map((button) => button.hasAttribute("disabled"))).toEqual([true, true]);
    fireEvent.click(yes);
    fireEvent.click(keep);
    expect(within(proposal).getByRole("group", { name: "Replace" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    await act(async () => {
      answer(new Response(JSON.stringify(PROPOSED), { status: 200 }));
      await pending;
    });
  });

  it("offers the coach only once the programs are known", async () => {
    let answer: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((done) => {
      answer = done;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => pending),
    );
    render(<App />);

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Ask the coach" })).not.toBeInTheDocument();
    await act(async () => {
      answer(new Response(JSON.stringify({ active: ACTIVE, proposed: null, next: null })));
      await pending;
    });
    expect(
      await screen.findByRole("heading", { name: "Change it with the coach" }),
    ).toBeInTheDocument();
  });

  it("does not offer the coach when the programs cannot be read", async () => {
    routeFetch({ [`GET ${PROGRAMS}`]: new TypeError("offline") });
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server");
    expect(screen.queryByRole("region", { name: "Ask the coach" })).not.toBeInTheDocument();
  });

  it("asks the coach for a program and shows the new proposal", async () => {
    let proposed: unknown = null;
    const reply = { role: "assistant", text: "Proposed: Full Body.", at: "2026-10-01T18:00:00Z" };
    const fetchMock = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "POST") {
        proposed = PROPOSED;
        return Promise.resolve(new Response(JSON.stringify(reply), { status: 200 }));
      }
      const body = { active: null, proposed, next: null };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const ask = await screen.findByRole("region", { name: "Ask the coach" });
    const box = within(ask).getByLabelText("What you want");
    const button = within(ask).getByRole("button", { name: "Ask" });
    expect(button).toBeDisabled();
    fireEvent.change(box, { target: { value: "   " } });
    expect(button).toBeDisabled();
    fireEvent.submit(box);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.change(box, { target: { value: " 3 days, full body " } });
    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
    });

    expect(await screen.findByText("Proposed: Full Body.")).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Proposed program" })).toBeInTheDocument();
    expect(screen.getByLabelText("What you want")).toHaveValue("");
    const [, init] = fetchMock.mock.calls[1] ?? [];
    expect(init?.body).toBe(JSON.stringify({ text: "Plan a program for me: 3 days, full body" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows the coach is working, and keeps the request if it fails", async () => {
    let answer: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((done) => {
      answer = done;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((_input, init) =>
        init?.method === "POST"
          ? pending
          : Promise.resolve(
              new Response(JSON.stringify({ active: ACTIVE, proposed: null, next: null })),
            ),
      ),
    );
    render(<App />);

    const ask = await screen.findByRole("region", { name: "Ask the coach" });
    await screen.findByRole("heading", { name: "Change it with the coach" });
    const box = within(ask).getByLabelText("What you want");
    fireEvent.change(box, { target: { value: "more legs" } });
    fireEvent.click(within(ask).getByRole("button", { name: "Ask" }));

    expect(within(ask).getByRole("status")).toHaveTextContent("The coach is working on it…");
    expect(within(ask).getByRole("button", { name: "Ask" })).toBeDisabled();
    fireEvent.submit(box); // a second request while one is out is ignored
    await act(async () => {
      answer(new Response(JSON.stringify({ detail: "the coach is not set up" }), { status: 503 }));
      await pending;
    });

    expect(await within(ask).findByRole("alert")).toHaveTextContent("The coach is not set up.");
    expect(box).toHaveValue("more legs");
  });
});
