import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "./App";
import { at, mockFetch, set } from "./test/fetch";

const WORKOUTS = [
  {
    id: 2,
    started_at: "2026-09-28T11:30:59+00:00",
    ended_at: null,
    exercises: ["Lat Pulldown", "Pull-up"],
    set_count: 4,
  },
  {
    id: 1,
    started_at: "2026-07-09T10:47:23+00:00",
    ended_at: null,
    exercises: ["Dead Hang"],
    set_count: 1,
  },
];

const WORKOUT_2 = {
  id: 2,
  started_at: "2026-09-28T11:30:59+00:00",
  ended_at: null,
  notes: "felt strong",
  exercises: [
    {
      position: 1,
      exercise_id: 45,
      name: "Lat Pulldown",
      measure: "reps",
      sets: [set(1, 12, 50), set(2, 8, 60, { rpe: 9, notes: "last rep slow" })],
    },
    {
      position: 2,
      exercise_id: 23,
      name: "Dead Hang",
      measure: "seconds",
      sets: [set(1, null, null, { duration_s: 50 })],
    },
  ],
};

const EXERCISES = [
  {
    id: 45,
    name: "Lat Pulldown",
    equipment: "cable",
    muscle_groups: "back,biceps",
    measure: "reps",
    workouts: 7,
    last_done: "2026-09-28T11:30:59+00:00",
    best_load_kg: 82.5,
  },
  {
    id: 17,
    name: "Pull-up",
    equipment: "bodyweight",
    muscle_groups: "back,biceps",
    measure: "reps",
    workouts: 1,
    last_done: "2026-09-16T10:00:00+00:00",
    best_load_kg: null,
  },
  {
    id: 99,
    name: "Arnold Press",
    equipment: null,
    muscle_groups: null,
    measure: "reps",
    workouts: 0,
    last_done: null,
    best_load_kg: null,
  },
];

const HISTORY_45 = {
  exercise: EXERCISES[0],
  sessions: [
    { workout_id: 2, started_at: "2026-09-28T11:30:59+00:00", sets: [set(1, 12, 50)] },
    { workout_id: 1, started_at: "2026-07-09T10:47:23+00:00", sets: [set(1, 10, 40)] },
  ],
};

function standardApi(): void {
  mockFetch({
    "/api/workouts": { body: WORKOUTS },
    "/api/workouts/2": { body: WORKOUT_2 },
    "/api/exercises": { body: EXERCISES },
    "/api/exercises/45/history": { body: HISTORY_45 },
  });
}

async function go(hash: string): Promise<void> {
  await act(async () => {
    window.location.hash = hash;
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

afterEach(() => {
  window.location.hash = "";
});

describe("History", () => {
  it("lists workouts newest first with a summary", async () => {
    standardApi();
    render(<App />);

    expect(screen.getByRole("heading", { level: 1, name: "History" })).toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    const links = await screen.findAllByRole("link", { name: /exercise/ });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "#/workouts/2",
      "#/workouts/1",
    ]);
    expect(links[0]).toHaveTextContent(
      "Tue 29 Sept 00:302 exercises · 4 setsLat Pulldown · Pull-up",
    );
    expect(links[1]).toHaveTextContent("1 exercise · 1 set");
  });

  it("says when there are no workouts", async () => {
    mockFetch({ "/api/workouts": { body: [] } });
    render(<App />);

    expect(await screen.findByText("No workouts yet.")).toBeInTheDocument();
  });

  it("shows an error when loading fails", async () => {
    mockFetch({ "/api/workouts": { status: 500, body: {} } });
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The server answered 500");
  });

  it("shows a workout with its sets", async () => {
    standardApi();
    await go("#/workouts/2");
    render(<App />);

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      "29 Sept 2026 00:30",
    );
    expect(screen.getByText("felt strong")).toBeInTheDocument();
    const blocks = screen.getAllByRole("listitem").filter((item) => item.className === "block");
    expect(blocks).toHaveLength(2);
    const pulldown = at(blocks, 0);
    const hang = at(blocks, 1);
    expect(within(pulldown).getByRole("link")).toHaveAttribute("href", "#/exercises/45");
    const chips = within(pulldown).getAllByRole("listitem");
    expect(chips.map((chip) => chip.textContent)).toEqual(["12 × 50 kg", "8 × 60 kg @9"]);
    expect(chips[1]).toHaveAttribute("title", "last rep slow");
    expect(chips[0]).not.toHaveAttribute("title");
    expect(within(hang).getByText("50 s")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "‹ History" })).toHaveAttribute("href", "#/");
  });

  it("omits notes when a workout has none", async () => {
    mockFetch({ "/api/workouts/2": { body: { ...WORKOUT_2, notes: null } } });
    await go("#/workouts/2");
    render(<App />);

    await screen.findByText("Lat Pulldown");
    expect(screen.queryByText("felt strong")).not.toBeInTheDocument();
  });

  it("reports a missing workout", async () => {
    mockFetch({});
    await go("#/workouts/404");
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Not found");
  });
});

describe("Exercises", () => {
  it("lists exercises with what is known about them", async () => {
    standardApi();
    await go("#/exercises");
    render(<App />);

    const cards = await screen.findAllByRole("link", { name: /workout/ });
    expect(cards.map((card) => card.textContent)).toEqual([
      "Lat Pulldown7 workouts · last Tue 29 Sept · best 82.5 kg",
      "Pull-up1 workout · last Wed 16 Sept",
      "Arnold Press0 workouts",
    ]);
  });

  it("filters by name, equipment or muscle group", async () => {
    standardApi();
    await go("#/exercises");
    render(<App />);
    await screen.findByText("Pull-up");
    const search = screen.getByRole("searchbox", { name: "Search exercises" });

    fireEvent.change(search, { target: { value: "  BODYWEIGHT " } });
    expect(screen.queryByText("Lat Pulldown")).not.toBeInTheDocument();
    expect(screen.getByText("Pull-up")).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "biceps" } });
    expect(screen.getByText("Lat Pulldown")).toBeInTheDocument();
    expect(screen.queryByText("Arnold Press")).not.toBeInTheDocument();
  });

  it("shows an exercise's sessions linking back to workouts", async () => {
    standardApi();
    await go("#/exercises/45");
    render(<App />);

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Lat Pulldown");
    expect(screen.getByText("7 workouts · last Tue 29 Sept · best 82.5 kg")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "29 Sept 2026" })).toHaveAttribute(
      "href",
      "#/workouts/2",
    );
    expect(screen.getByText("10 × 40 kg")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "‹ Exercises" })).toHaveAttribute(
      "href",
      "#/exercises",
    );
  });
});

describe("Navigation", () => {
  it("marks the current section and switches on hash change", async () => {
    standardApi();
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(within(nav).getByRole("link", { name: "History" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Exercises" })).not.toHaveAttribute(
      "aria-current",
    );

    await go("#/exercises/45");

    expect(within(nav).getByRole("link", { name: "Exercises" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Lat Pulldown");
  });
});
