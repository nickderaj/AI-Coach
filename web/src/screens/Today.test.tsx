import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { addBlock, newDraft, todayDraft } from "../log/draft";
import { renderLogging, routeFetch, writes } from "../test/logging";
import { TODAY, UPPER } from "../test/today";
import { targetLine } from "./Log";

const NOW = new Date("2026-10-01T07:00:00Z");
const BENCH = { id: 7, name: "Bench Press", measure: "reps" as const, equipment: "barbell" };

async function go(hash: string): Promise<void> {
  await act(async () => {
    window.location.hash = hash;
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
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
    last: true,
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
    routeFetch({ "GET /api/today": { body: TODAY } });
    const { outbox, drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Start this workout" }));
    await go(window.location.hash);

    expect(window.location.hash).toBe("#/log");
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
    fireEvent.click(within(bench).getByRole("button", { name: "Set 1 done" }));
    expect(drafts.get()?.restUntil).toBe(NOW.getTime() + 120_000);
    const row = within(superset).getByRole("region", { name: "Cable Row" });
    fireEvent.click(within(row).getByRole("button", { name: "Set 1 done" }));
    expect(drafts.get()?.restUntil).toBe(NOW.getTime() + 120_000);
    const hang = within(superset).getByRole("region", { name: "Dead Hang" });
    fireEvent.click(within(hang).getByRole("button", { name: "Set 1 done" }));
    expect(drafts.get()?.restUntil).toBe(NOW.getTime() + 60_000);

    const sets = writes(outbox).slice(1);
    expect(
      sets.map(([, body]) => (body as { block_exercise_id: number }).block_exercise_id),
    ).toEqual([1, 2, 3]);
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

  it("picks the day's workout back up from the server", async () => {
    routeFetch({
      "GET /api/today": { body: { ...TODAY, workout_client_id: "w9" } },
      "GET /api/workouts/current": {
        body: {
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
        },
      },
    });
    const { outbox, drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume this workout" }));
    await vi.waitFor(() => {
      expect(window.location.hash).toBe("#/log");
    });

    const draft = drafts.get();
    expect([draft?.id, draft?.started_at, draft?.program]).toEqual([
      "w9",
      "2026-10-01T06:30:00+00:00",
      { day_id: 11, week: 2 },
    ]);
    expect(draft?.blocks[0]?.sets.map((set) => set.logged?.reps)).toEqual(["9"]);
    expect(writes(outbox)).toEqual([]);
  });

  it("starts afresh if the server's workout has just been finished", async () => {
    routeFetch({
      "GET /api/today": { body: { ...TODAY, workout_client_id: "w9" } },
      "GET /api/workouts/current": { body: null },
    });
    const { drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume this workout" }));
    await vi.waitFor(() => {
      expect(drafts.get()?.id).toBe("w9");
    });
    expect(drafts.get()?.started_at).toBe(NOW.toISOString());
  });

  it("needs a connection to pick it back up", async () => {
    routeFetch({
      "GET /api/today": { body: { ...TODAY, workout_client_id: "w9" } },
      "GET /api/workouts/current": new TypeError("offline"),
    });
    const { drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Resume this workout" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Picking the workout back up needs a connection.",
    );
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
