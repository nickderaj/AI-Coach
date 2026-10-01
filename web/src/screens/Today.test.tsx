import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import { App } from "../App";
import { addBlock, newDraft, todayDraft } from "../log/draft";
import type { Draft } from "../log/draft";
import { finishedHere, markFinished } from "../log/finished";
import { renderLogging, routeFetch, writes } from "../test/logging";
import { TODAY, UPPER } from "../test/today";
import { targetLine } from "./Log";
import { FINISHED_HERE, LEFT_OVER, RESUME_OFFLINE } from "./Today";

const NOW = new Date("2026-10-01T07:00:00Z");
const BENCH = { id: 7, name: "Bench Press", measure: "reps" as const, equipment: "barbell" };

async function go(hash: string): Promise<void> {
  await act(async () => {
    window.location.hash = hash;
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

type Answer = unknown;

/**
 * Replace fetch with answers given in turn per "METHOD path", the last one
 * repeated; an Error answers as a network failure.
 */
function sequence(routes: Record<string, Answer[]>): Mock<typeof fetch> {
  const seen = new Map<string, number>();
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const key = `${init?.method ?? "GET"} ${pathOf(input)}`;
    const answers = routes[key] ?? [];
    const count = seen.get(key) ?? 0;
    seen.set(key, count + 1);
    return reply(answers, count);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function pathOf(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return input;
  }
  return input instanceof URL ? input.pathname : input.url;
}

/** An answer with a status other than 200. */
class Refusal {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    this.status = status;
    this.body = body;
  }
}

/** A 200 answer that is not JSON, as from a proxy's error page. */
class Raw {
  readonly text: string;

  constructor(text: string) {
    this.text = text;
  }
}

function reply(answers: Answer[], count: number): Promise<Response> {
  if (answers.length === 0) {
    return Promise.resolve(new Response("{}", { status: 404 }));
  }
  const answer = answers[Math.min(count, answers.length - 1)];
  if (answer instanceof Error) {
    return Promise.reject(answer);
  }
  if (answer instanceof Raw) {
    return Promise.resolve(new Response(answer.text, { status: 200 }));
  }
  if (answer instanceof Refusal) {
    return Promise.resolve(new Response(JSON.stringify(answer.body), { status: answer.status }));
  }
  return Promise.resolve(new Response(JSON.stringify(answer), { status: 200 }));
}

/** The server's copy of this day's workout, w9, with one bench set logged. */
function serverWorkout(): Record<string, unknown> {
  return {
    id: 5,
    started_at: "2026-10-01T06:30:00+00:00",
    ended_at: null,
    notes: null,
    client_id: "w9",
    program_day_id: 11,
    program_week: 2,
    exercises: [
      {
        position: 1,
        exercise_id: 101,
        name: "Bench Press",
        measure: "reps",
        carried_kg: 0,
        block_exercise_id: 1,
        sets: [
          {
            set_number: 1,
            reps: 9,
            load_kg: 62.5,
            duration_s: null,
            rpe: null,
            notes: null,
            client_id: "a",
          },
        ],
      },
    ],
  };
}

/** The draft rebuilt from `serverWorkout()`: its sets in place, the rest still to do. */
function expectResumed(draft: Draft | null): void {
  expect([draft?.id, draft?.started_at, draft?.program]).toEqual([
    "w9",
    "2026-10-01T06:30:00+00:00",
    { day_id: 11, week: 2 },
  ]);
  const bench = draft?.blocks[0]?.sets ?? [];
  // One of three bench sets was logged; the other two keep their targets.
  expect(bench.map((set) => [set.logged?.reps, set.reps])).toEqual([
    ["9", "9"],
    [undefined, "8"],
    [undefined, "8"],
  ]);
  expect(draft?.blocks.map((block) => block.sets.length)).toEqual([3, 2, 2]);
}

let counter = 0;
function ids(): string {
  counter += 1;
  return `id-${String(counter)}`;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  window.location.hash = "#/today";
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.location.hash = "";
  localStorage.clear();
});

describe("targetLine", () => {
  const plan = {
    label: "A",
    group: 0,
    rest_s: 90,
    rep_min: 5,
    rep_max: 5,
    target: { decision: "repeat" as const, load_kg: 100, reps: [5, 5, 5, 5, 5] },
  };

  it("writes one number for a range of one, and leaves out no load", () => {
    expect(targetLine(plan, "reps")).toBe("Target 5 × 5 · 100 kg");
    expect(targetLine({ ...plan, target: { ...plan.target, load_kg: 0 } }, "reps")).toBe(
      "Target 5 × 5",
    );
    expect(targetLine({ ...plan, target: { ...plan.target, load_kg: null } }, "seconds")).toBe(
      "Target 5 × 5 s",
    );
  });
});

describe("Today", () => {
  it("points to the Program tab without a program", async () => {
    routeFetch({ "GET /api/today": { body: null } });
    renderLogging();

    expect(await screen.findByText("No program yet. Ask the coach for one.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Program ›" })).toHaveAttribute("href", "#/program");
    expect(screen.getByRole("link", { name: "‹ Home" })).toHaveAttribute("href", "#/");
  });

  it("says when the block is done", async () => {
    routeFetch({ "GET /api/today": { body: { ...TODAY, day: null } } });
    renderLogging();

    expect(
      await screen.findByText("Block complete. Ask the coach for your next program."),
    ).toBeInTheDocument();
  });

  it("shows the day with each exercise's target and last time", async () => {
    routeFetch({ "GET /api/today": { body: TODAY } });
    renderLogging();

    expect(await screen.findByRole("heading", { level: 1, name: "Upper A" })).toBeInTheDocument();
    expect(screen.getByText("Day 1 of 4")).toBeInTheDocument();
    expect(screen.getByText("Week 2 of 6 · Upper / Lower")).toHaveClass("muted");
    const lines = [...document.querySelectorAll(".planned")].map((line) => line.textContent);
    expect(lines).toEqual([
      "A Bench PressTarget 3 × 8–12 · 62.5 kgLast Thu 24 Sept: 12 × 60 kg",
      "B1 Cable RowTarget 2 × 8–12 · 40 kgNot done before",
      "B2 Dead HangTarget 2 × 30–45 sNot done before",
    ]);
    expect(screen.getByText("Superset")).toBeInTheDocument();
    expect(screen.getByText("Rest 120 s")).toBeInTheDocument();
    expect(screen.getByText("Rest 60 s")).toBeInTheDocument();
  });

  it("marks the deload week", async () => {
    routeFetch({ "GET /api/today": { body: { ...TODAY, day: { ...UPPER, deload: true } } } });
    renderLogging();

    expect(await screen.findByText("Deload week: fewer sets, lighter · Upper / Lower")).toHaveClass(
      "deload",
    );
  });

  it("can only be looked at where logging is not possible", async () => {
    routeFetch({ "GET /api/today": { body: TODAY } });
    render(<App />);

    expect(await screen.findByRole("heading", { level: 1, name: "Upper A" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start this workout" })).not.toBeInTheDocument();
  });

  it("starts the day prefilled from its targets, and trains it", async () => {
    const fetchMock = sequence({ "GET /api/today": [TODAY, TODAY] });
    const { outbox, drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Start this workout" }));
    await vi.waitFor(() => {
      expect(window.location.hash).toBe("#/log");
    });
    await go(window.location.hash);

    // The day was checked with the server, not a saved copy, before starting.
    const reads = fetchMock.mock.calls.filter(([path]) => path === "/api/today");
    expect(reads.map(([, init]) => init?.cache)).toEqual([undefined, "no-store"]);
    const draft = drafts.get();
    expect(draft?.program).toEqual({ day_id: 11, week: 2 });
    expect(writes(outbox)).toEqual([
      [
        `PUT /api/workouts/${draft?.id ?? ""}`,
        { started_at: "2026-10-01T07:00:00.000Z", program: { day_id: 11, week: 2 } },
      ],
    ]);

    expect(screen.getByRole("heading", { level: 1, name: "Upper A · Week 2" })).toBeInTheDocument();
    const bench = screen.getByRole("region", { name: "Bench Press" });
    expect(within(bench).getByText("Target 3 × 8–12 · 62.5 kg")).toBeInTheDocument();
    expect(within(bench).getByText("Up: every set reached the top last time")).toHaveClass(
      "progress",
    );
    expect(within(bench).getByLabelText("Set 1 kg")).toHaveValue("62.5");
    expect(within(bench).getByLabelText("Set 1 reps")).toHaveValue("8");
    expect(within(bench).getByText("12 × 60 kg")).toBeInTheDocument(); // previous
    const superset = screen.getByRole("group", { name: "Superset" });
    expect(
      within(superset).getByText("Superset: one set of each in turn, then rest 60 s"),
    ).toBeInTheDocument();
    expect(
      within(superset)
        .getAllByRole("region")
        .map((card) => card.getAttribute("aria-label")),
    ).toEqual(["Cable Row", "Dead Hang"]);
    expect(within(superset).getByText("Same load: beat last time")).toBeInTheDocument();
    expect(within(superset).getByText("First time in this program")).toBeInTheDocument();

    // Bench rests its own 120 s; a superset rests only after its round.
    const ticked = Date.now();
    fireEvent.click(within(bench).getByRole("button", { name: "Set 1 done" }));
    expect(drafts.get()?.restUntil).toBe(ticked + 120_000);
    const row = within(superset).getByRole("region", { name: "Cable Row" });
    fireEvent.click(within(row).getByRole("button", { name: "Set 1 done" }));
    expect(drafts.get()?.restUntil).toBe(ticked + 120_000);
    const hang = within(superset).getByRole("region", { name: "Dead Hang" });
    fireEvent.click(within(hang).getByRole("button", { name: "Set 1 done" }));
    expect(drafts.get()?.restUntil).toBe(ticked + 60_000);

    const sets = writes(outbox).slice(1);
    expect(
      sets.map(([, body]) => (body as { block_exercise_id: number }).block_exercise_id),
    ).toEqual([1, 2, 3]);

    // Finishing it marks the day done on this phone.
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(finishedHere(localStorage, 11, 2)).toBe(true);
    expect(finishedHere(localStorage, 11, 3)).toBe(false);
  });

  it.each([
    ["the server has moved on to another day", { ...TODAY, day: { ...UPPER, id: 12 } }],
    ["the server has moved on to another week", { ...TODAY, day: { ...UPPER, week: 3 } }],
    ["the day is already being trained", { ...TODAY, workout_client_id: "w8" }],
    ["the block is done", { ...TODAY, day: null }],
    ["there is no program any more", null],
  ])("does not start a day when %s", async (_why, fresh) => {
    sequence({ "GET /api/today": [TODAY, fresh] });
    const { outbox, drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Start this workout" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "The plan had changed since this screen was loaded. This is the current one.",
    );
    expect(drafts.get()).toBeNull();
    expect(writes(outbox)).toEqual([]);
    expect(window.location.hash).toBe("#/today");
  });

  it("starts from the saved plan without signal", async () => {
    sequence({ "GET /api/today": [TODAY, new TypeError("offline")] });
    const { drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Start this workout" }));

    await vi.waitFor(() => {
      expect(drafts.get()?.program).toEqual({ day_id: 11, week: 2 });
    });
  });

  it.each([
    [new Refusal(403, { detail: "forbidden" }), "The server answered 403"],
    [new Refusal(500, "oops"), "The server answered 500"],
    [{ program_id: "not a plan" }, "The server sent data this app does not understand"],
    [new Raw("<html>Bad gateway</html>"), "The server sent data this app does not understand"],
  ])("does not start offline when the server refuses or is not understood", async (fresh, why) => {
    // Only a network failure falls back to the saved plan; anything else is shown.
    sequence({ "GET /api/today": [TODAY, fresh] });
    const { drafts, outbox } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Start this workout" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(why);
    expect(drafts.get()).toBeNull();
    expect(writes(outbox)).toEqual([]);
  });

  it("says why the server's workout could not be read", async () => {
    sequence({
      "GET /api/today": [{ ...TODAY, workout_client_id: "w9" }],
      "GET /api/workouts/current": [new Refusal(500, "oops")],
    });
    const { drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume this workout" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The server answered 500");
    expect(drafts.get()).toBeNull();
  });

  it("never starts a day again that this phone has finished, without signal", async () => {
    markFinished(localStorage, 11, 2);
    sequence({ "GET /api/today": [TODAY, new TypeError("offline")] });
    const { drafts, outbox } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Start this workout" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(FINISHED_HERE);
    expect(drafts.get()).toBeNull();
    expect(writes(outbox)).toEqual([]);
    expect(screen.getByRole("button", { name: "Start this workout" })).toBeEnabled();
  });

  it("goes back to the day's workout already on this phone", async () => {
    routeFetch({ "GET /api/today": { body: TODAY } });
    const draft = todayDraft(
      { id: "w1", started_at: NOW.toISOString(), program_name: "Upper / Lower" },
      UPPER,
      ids,
    );
    renderLogging(draft);

    expect(await screen.findByRole("link", { name: "Resume ›" })).toHaveAttribute("href", "#/log");
    expect(screen.queryByText("Another workout is in progress.")).not.toBeInTheDocument();
  });

  it("says when another workout is in progress", async () => {
    routeFetch({ "GET /api/today": { body: TODAY } });
    renderLogging(addBlock(newDraft("w1", NOW), { block: "b", set: "s" }, BENCH, []));

    expect(await screen.findByText("Another workout is in progress.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start this workout" })).not.toBeInTheDocument();
  });

  it("picks the day's workout back up from the server, keeping the sets still to do", async () => {
    const fetchMock = sequence({
      "GET /api/today": [{ ...TODAY, workout_client_id: "w9" }],
      "GET /api/workouts/current": [serverWorkout()],
    });
    const { outbox, drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume this workout" }));
    await vi.waitFor(() => {
      expect(window.location.hash).toBe("#/log");
    });

    expect(fetchMock.mock.calls.at(-1)?.[1]?.cache).toBe("no-store");
    expect(writes(outbox)).toEqual([]);
    expectResumed(drafts.get());
  });

  it("picks up a day started with nothing logged yet", async () => {
    sequence({
      "GET /api/today": [{ ...TODAY, workout_client_id: "w9" }],
      "GET /api/workouts/current": [{ ...serverWorkout(), exercises: [] }],
    });
    const { drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume this workout" }));
    await vi.waitFor(() => {
      expect(drafts.get()?.id).toBe("w9");
    });

    expect(drafts.get()?.blocks.map((block) => block.sets.length)).toEqual([3, 2, 2]);
    expect(drafts.get()?.blocks[0]?.plan?.label).toBe("A");
  });

  it.each([
    ["it has been finished", null],
    ["another workout is in progress", { ...serverWorkout(), client_id: "w7" }],
    ["it trains another day", { ...serverWorkout(), program_day_id: 12 }],
    ["it trains another week", { ...serverWorkout(), program_week: 3 }],
  ])("does not pick up the server's workout when %s", async (_why, current) => {
    sequence({
      "GET /api/today": [{ ...TODAY, workout_client_id: "w9" }, TODAY],
      // As the screen loaded it, then as it is when asked afresh.
      "GET /api/workouts/current": [serverWorkout(), current, null],
    });
    const { drafts, outbox } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume this workout" }));

    expect(await screen.findByRole("status")).toHaveTextContent("The plan had changed");
    expect(await screen.findByRole("button", { name: "Start this workout" })).toBeInTheDocument();
    expect(drafts.get()).toBeNull();
    expect(writes(outbox)).toEqual([]);
  });

  it("offers an unfinished workout of a replaced program, and holds the day for it", async () => {
    // A database from before replacing a program mid-workout was refused.
    const left = { ...serverWorkout(), client_id: "w5", program_day_id: 3, program_week: 6 };
    sequence({ "GET /api/today": [TODAY], "GET /api/workouts/current": [left] });
    const { drafts, outbox } = renderLogging();

    const card = await screen.findByRole("region", { name: "Unfinished workout" });
    expect(card).toHaveTextContent(LEFT_OVER);
    expect(card).toHaveTextContent("Started Thu 1 Oct, 19:30");
    expect(screen.queryByRole("button", { name: "Start this workout" })).not.toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "Resume it as logged" }));
    await vi.waitFor(() => {
      expect(window.location.hash).toBe("#/log");
    });

    const draft = drafts.get();
    expect([draft?.id, draft?.program]).toEqual(["w5", { day_id: 3, week: 6 }]);
    expect(draft?.blocks[0]?.slot_id).toBe(1);
    expect(writes(outbox)).toEqual([]);
  });

  it("re-checks the left-over workout before picking it up", async () => {
    const left = { ...serverWorkout(), client_id: "w5", program_day_id: 3, program_week: 6 };
    sequence({
      "GET /api/today": [TODAY],
      "GET /api/workouts/current": [left, null],
    });
    const { drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume it as logged" }));

    expect(await screen.findByRole("status")).toHaveTextContent("The plan had changed");
    expect(drafts.get()).toBeNull();
    expect(await screen.findByRole("button", { name: "Start this workout" })).toBeInTheDocument();
  });

  it.each([
    [new TypeError("offline"), RESUME_OFFLINE],
    [new Refusal(500, "oops"), "The server answered 500"],
  ])("says why the left-over workout could not be read", async (failure, why) => {
    const left = { ...serverWorkout(), client_id: "w5", program_day_id: 3, program_week: 6 };
    sequence({ "GET /api/today": [TODAY], "GET /api/workouts/current": [left, failure] });
    const { drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume it as logged" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(why);
    expect(drafts.get()).toBeNull();
  });

  it("shows the left-over workout even with no day to train", async () => {
    const left = { ...serverWorkout(), client_id: "w5", program_day_id: 3, program_week: 6 };
    sequence({ "GET /api/today": [{ ...TODAY, day: null }], "GET /api/workouts/current": [left] });
    render(<App />);

    expect(await screen.findByRole("region", { name: "Unfinished workout" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume it as logged" })).not.toBeInTheDocument();
  });

  it("leaves the left-over workout to Resume once this phone has a workout", async () => {
    const left = { ...serverWorkout(), client_id: "w5", program_day_id: 3, program_week: 6 };
    sequence({ "GET /api/today": [TODAY], "GET /api/workouts/current": [left] });
    renderLogging(addBlock(newDraft("w5", NOW), { block: "b", set: "s" }, BENCH, []));

    expect(await screen.findByRole("link", { name: "Resume ›" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Unfinished workout" })).not.toBeInTheDocument();
  });

  it("needs a connection to pick it back up", async () => {
    sequence({
      "GET /api/today": [{ ...TODAY, workout_client_id: "w9" }],
      "GET /api/workouts/current": [new TypeError("offline")],
    });
    const { drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume this workout" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(RESUME_OFFLINE);
    expect(drafts.get()).toBeNull();
  });
});

describe("Home", () => {
  it("points to the next program day", async () => {
    window.location.hash = "";
    routeFetch({
      "GET /api/today": { body: TODAY },
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": { body: null },
    });
    renderLogging();

    const card = await screen.findByRole("link", { name: /Next in your program/ });
    expect(card).toHaveAttribute("href", "#/today");
    expect(card).toHaveTextContent("Upper A · Week 2");
  });

  it("names the deload week, and says nothing without a next day", async () => {
    window.location.hash = "";
    routeFetch({
      "GET /api/today": { body: { ...TODAY, day: { ...UPPER, deload: true, week: 7 } } },
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": { body: null },
    });
    renderLogging();

    expect(await screen.findByRole("link", { name: /Next in your program/ })).toHaveTextContent(
      "Upper A · Deload week",
    );
  });

  it("picks up a program day in progress through Today", async () => {
    window.location.hash = "";
    routeFetch({
      "GET /api/today": { body: { ...TODAY, workout_client_id: "w9" } },
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": { body: serverWorkout() },
    });
    renderLogging();

    const link = await screen.findByRole("link", {
      name: /Resume the unfinished program workout from/,
    });
    expect(link).toHaveAttribute("href", "#/today");
    expect(
      screen.queryByRole("button", { name: /Resume the unfinished workout/ }),
    ).not.toBeInTheDocument();
  });

  it("picks up a program day through Today even when Today's copy names another", async () => {
    // The two reads can be saved copies from different moments: the workout's own
    // program day decides, and Today checks it afresh.
    window.location.hash = "";
    routeFetch({
      "GET /api/today": { body: TODAY },
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": { body: serverWorkout() },
    });
    const { drafts } = renderLogging();

    expect(
      await screen.findByRole("link", { name: /Resume the unfinished program workout from/ }),
    ).toHaveAttribute("href", "#/today");
    expect(screen.queryByRole("button", { name: /Resume the unfinished/ })).not.toBeInTheDocument();
    expect(drafts.get()).toBeNull();
  });

  it("picks up a workout outside any program as it is", async () => {
    window.location.hash = "";
    routeFetch({
      "GET /api/today": { body: null },
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": {
        body: { ...serverWorkout(), program_day_id: null, program_week: null },
      },
    });
    const { drafts } = renderLogging();

    fireEvent.click(
      await screen.findByRole("button", { name: /Resume the unfinished workout from/ }),
    );

    expect(drafts.get()?.id).toBe("w9");
    expect(drafts.get()?.program).toBeNull();
  });

  it("shows no card once the block is done", async () => {
    window.location.hash = "";
    routeFetch({
      "GET /api/today": { body: { ...TODAY, day: null } },
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": { body: null },
    });
    renderLogging();

    expect(await screen.findByRole("button", { name: "Start workout" })).toBeInTheDocument();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.queryByText("Next in your program")).not.toBeInTheDocument();
  });
});
