import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { at, mockFetch, set } from "./test/fetch";

// Tests run in Pacific/Auckland (UTC+13): 2026-09-28T11:30Z is Tue 29 Sept, 00:30.
const NOW = new Date("2026-09-30T08:00:00Z"); // Wed 30 Sept, 21:00 local

const WORKOUTS = [
  {
    id: 2,
    started_at: "2026-09-28T11:30:59+00:00",
    ended_at: "2026-09-28T12:42:00+00:00",
    exercises: [
      {
        position: 1,
        name: "Lat Pulldown",
        measure: "reps",
        sets: 2,
        best: set(2, 8, 60, { rpe: 9 }),
      },
      {
        position: 2,
        name: "Dead Hang",
        measure: "seconds",
        sets: 1,
        best: set(1, null, null, { duration_s: 50 }),
      },
    ],
    set_count: 3,
    volume_kg: 1080,
  },
  {
    id: 1,
    started_at: "2026-07-09T10:47:23+00:00",
    ended_at: null,
    exercises: [{ position: 1, name: "Pull-up", measure: "reps", sets: 1, best: set(1, 8, null) }],
    set_count: 1,
    volume_kg: 0,
  },
];

const WORKOUT_2 = {
  id: 2,
  started_at: "2026-09-28T11:30:59+00:00",
  ended_at: "2026-09-28T12:42:00+00:00",
  notes: "felt strong",
  client_id: null,
  exercises: [
    {
      position: 1,
      exercise_id: 45,
      name: "Lat Pulldown",
      measure: "reps",
      carried_kg: 0,
      sets: [set(1, 12, 50), set(2, 8, 60, { rpe: 9, notes: "last rep slow" })],
    },
    {
      position: 2,
      exercise_id: 23,
      name: "Dead Hang",
      measure: "seconds",
      carried_kg: 65,
      sets: [set(1, null, null, { duration_s: 50 })],
    },
  ],
};

const PULLDOWN = {
  id: 45,
  name: "Lat Pulldown",
  equipment: "cable",
  muscle_groups: "back,biceps",
  measure: "reps",
  workouts: 7,
  last_done: "2026-09-28T11:30:59+00:00",
  best_load_kg: 82.5,
};

const EXERCISES = [
  PULLDOWN,
  {
    id: 17,
    name: "Pull-up",
    equipment: "bodyweight",
    muscle_groups: "back,biceps",
    measure: "reps",
    workouts: 1,
    last_done: "2026-07-09T10:47:23+00:00",
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
  exercise: PULLDOWN,
  carried_kg: 0,
  sessions: [
    {
      workout_id: 2,
      position: 1,
      started_at: "2026-09-28T11:30:59+00:00",
      sets: [set(1, 12, 50), set(2, 8, 60)],
    },
    {
      workout_id: 3,
      position: 1,
      started_at: "2026-08-01T00:00:00+00:00",
      sets: [set(1, 15, null)],
    },
    { workout_id: 1, position: 1, started_at: "2026-07-09T10:47:23+00:00", sets: [set(1, 10, 40)] },
  ],
};

const HISTORY_23 = {
  exercise: {
    ...PULLDOWN,
    id: 23,
    name: "Dead Hang",
    equipment: "bodyweight",
    measure: "seconds",
    workouts: 1,
    best_load_kg: null,
  },
  carried_kg: 65,
  sessions: [
    {
      workout_id: 2,
      position: 2,
      started_at: "2026-09-28T11:30:59+00:00",
      sets: [set(1, null, null, { duration_s: 50 })],
    },
  ],
};

function standardApi(): void {
  mockFetch({
    "/api/workouts?limit=500": { body: WORKOUTS },
    "/api/workouts/2": { body: WORKOUT_2 },
    "/api/exercises": { body: EXERCISES },
    "/api/exercises/45/history": { body: HISTORY_45 },
    "/api/exercises/23/history": { body: HISTORY_23 },
  });
}

async function go(hash: string): Promise<void> {
  await act(async () => {
    window.location.hash = hash;
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const text = (elements: Element[]): (string | null)[] => elements.map((e) => e.textContent);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
  window.location.hash = "";
});

describe("Home", () => {
  it("shows this week's numbers, weekly volume and recent workouts", async () => {
    standardApi();
    render(<App />);

    expect(screen.getByText("Good evening")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Your training" })).toBeInTheDocument();
    expect(await screen.findByText("this week")).toBeInTheDocument();
    const tiles = document.querySelectorAll(".tile");
    expect(text([...tiles])).toEqual(["1this week", "1week streak", "1,080kg this week"]);
    const chart = screen.getByRole("img", { name: "Volume lifted per week, last 8 weeks" });
    expect(text([...chart.querySelectorAll(".bar text")])).toEqual([
      "10/08",
      "17/08",
      "24/08",
      "31/08",
      "07/09",
      "14/09",
      "21/09",
      "28/09",
    ]);
    expect(chart.querySelectorAll(".bar.current")).toHaveLength(1);
    expect(document.querySelectorAll("a.card")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "All workouts ›" })).toHaveAttribute(
      "href",
      "#/history",
    );
  });

  it("uses the plural for a longer streak", async () => {
    mockFetch({
      "/api/workouts?limit=500": {
        body: [
          { ...at(WORKOUTS, 0), id: 3 },
          { ...at(WORKOUTS, 1), id: 4, started_at: "2026-09-21T00:00:00Z" },
        ],
      },
    });
    render(<App />);

    expect(await screen.findByText("weeks streak")).toBeInTheDocument();
  });

  it("says when there are no workouts", async () => {
    mockFetch({ "/api/workouts?limit=500": { body: [] } });
    render(<App />);

    expect(await screen.findByText("No workouts yet.")).toBeInTheDocument();
    expect(text([...document.querySelectorAll(".tile strong")])).toEqual(["0", "0", "0"]);
  });

  it("shows an error when loading fails", async () => {
    mockFetch({ "/api/workouts?limit=500": { status: 500, body: {} } });
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The server answered 500");
  });
});

describe("History", () => {
  it("lists workout cards with duration, volume and best sets", async () => {
    standardApi();
    await go("#/history");
    render(<App />);

    const cards = await screen.findAllByRole("link", { name: /workout/ });
    expect(cards.map((card) => card.getAttribute("href"))).toEqual([
      "#/workouts/2",
      "#/workouts/1",
    ]);
    const first = at(cards, 0);
    expect(within(first).getByText("Morning workout")).toBeInTheDocument();
    expect(within(first).getByText("Tue 29 Sept · 00:30")).toBeInTheDocument();
    expect(text(within(first).getAllByRole("listitem"))).toEqual([
      "⏱ 1 h 11 min",
      "🏋 1,080 kg",
      "3 sets",
      "2 × Lat Pulldown8 × 60 kg",
      "1 × Dead Hang50 s",
    ]);
    const second = at(cards, 1);
    expect(within(second).getByText("Evening workout")).toBeInTheDocument();
    expect(text(within(second).getAllByRole("listitem"))).toEqual([
      "🏋 0 kg",
      "1 set",
      "1 × Pull-up8 reps",
    ]);
  });

  it("says when there are no workouts", async () => {
    mockFetch({ "/api/workouts?limit=500": { body: [] } });
    await go("#/history");
    render(<App />);

    expect(await screen.findByText("No workouts yet.")).toBeInTheDocument();
  });

  it("shows a workout with a table of sets per exercise", async () => {
    standardApi();
    await go("#/workouts/2");
    render(<App />);

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Morning workout");
    expect(screen.getByText("29 Sept 2026 · 00:30")).toBeInTheDocument();
    expect(screen.getByText("felt strong")).toBeInTheDocument();
    expect(text([...document.querySelectorAll(".meta .pill")])).toEqual([
      "⏱ 1 h 11 min",
      "🏋 1,080 kg",
      "3 sets",
    ]);
    const [pulldown, hang] = screen.getAllByRole("table");
    expect(screen.getByRole("link", { name: "Lat Pulldown" })).toHaveAttribute(
      "href",
      "#/exercises/45",
    );
    const rows = within(pulldown ?? document.body).getAllByRole("row");
    expect(text(rows)).toEqual(["SetReps × kgRPE", "112 × 50 kg–", "28 × 60 kg9"]);
    expect(at(rows, 2)).toHaveAttribute("title", "last rep slow");
    expect(at(rows, 1)).not.toHaveAttribute("title");
    // No set of the hang has an RPE, so its table has no RPE column.
    expect(text(within(hang ?? document.body).getAllByRole("row"))).toEqual(["SetTime", "150 s"]);
    expect(screen.getByRole("link", { name: "‹ History" })).toHaveAttribute("href", "#/history");
  });

  it("counts body weight in a workout's volume", async () => {
    mockFetch({
      "/api/workouts/2": {
        body: {
          ...WORKOUT_2,
          exercises: [
            {
              position: 1,
              exercise_id: 17,
              name: "Pull-up",
              measure: "reps",
              carried_kg: 65,
              sets: [set(1, 10, null), set(2, 8, 10)],
            },
          ],
        },
      },
    });
    await go("#/workouts/2");
    render(<App />);

    expect(await screen.findByText("🏋 1,250 kg")).toBeInTheDocument(); // 10 × 65 + 8 × 75
  });

  it("omits notes and duration when there are none", async () => {
    mockFetch({
      "/api/workouts/2": { body: { ...WORKOUT_2, notes: null, ended_at: null } },
    });
    await go("#/workouts/2");
    render(<App />);

    await screen.findByText("Lat Pulldown");
    expect(screen.queryByText("felt strong")).not.toBeInTheDocument();
    expect(text([...document.querySelectorAll(".meta .pill")])).toEqual(["🏋 1,080 kg", "3 sets"]);
  });

  it("reports a missing workout", async () => {
    mockFetch({});
    await go("#/workouts/404");
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Not found");
  });
});

describe("Exercises", () => {
  it("lists exercises with avatars and what is known about them", async () => {
    standardApi();
    await go("#/exercises");
    render(<App />);

    const rows = await screen.findAllByRole("link", { name: /workout/ });
    expect(text(rows)).toEqual([
      "LPLat Pulldown7 workouts · last Tue 29 Sept · best 82.5 kg",
      "PPull-up1 workout · last Thu 9 Jul",
      "APArnold Press0 workouts",
    ]);
  });

  it("filters by search text and by equipment", async () => {
    standardApi();
    await go("#/exercises");
    render(<App />);
    await screen.findByText("Pull-up");
    const chips = within(screen.getByRole("group", { name: "Equipment" })).getAllByRole("button");
    expect(text(chips)).toEqual(["bodyweight", "cable"]);

    fireEvent.change(screen.getByRole("searchbox", { name: "Search exercises" }), {
      target: { value: "  BICEPS " },
    });
    expect(screen.queryByText("Arnold Press")).not.toBeInTheDocument();
    expect(screen.getByText("Lat Pulldown")).toBeInTheDocument();

    fireEvent.click(at(chips, 0));
    expect(at(chips, 0)).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Lat Pulldown")).not.toBeInTheDocument();
    expect(screen.getByText("Pull-up")).toBeInTheDocument();

    fireEvent.click(at(chips, 0));
    expect(at(chips, 0)).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Lat Pulldown")).toBeInTheDocument();
  });

  it("charts progress and shows personal records", async () => {
    standardApi();
    await go("#/exercises/45");
    render(<App />);

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Lat Pulldown");
    expect(screen.getByText("cable · 7 workouts")).toBeInTheDocument();
    const chart = screen.getByRole("img", { name: "Heaviest per session" });
    expect(text([...chart.querySelectorAll("circle title")])).toEqual([
      "9 Jul: 40 kg",
      "29 Sept: 60 kg",
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Est. 1RM" }));

    expect(screen.getByRole("img", { name: "Est. 1RM per session" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Est. 1RM" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(text([...document.querySelectorAll(".records .tile")])).toEqual([
      "60 kgHeaviest",
      "76 kgEst. 1RM",
      "1,080 kgVolume",
      "15 repsMost reps", // from the session without a load
    ]);
    expect(screen.getByRole("link", { name: "9 Jul 2026" })).toHaveAttribute(
      "href",
      "#/workouts/1",
    );
    expect(screen.getByRole("link", { name: "‹ Exercises" })).toHaveAttribute(
      "href",
      "#/exercises",
    );
  });

  it("charts a repeated exercise in workout order", async () => {
    mockFetch({
      "/api/exercises/45/history": {
        body: {
          exercise: PULLDOWN,
          carried_kg: 0,
          sessions: [
            {
              workout_id: 2,
              position: 1,
              started_at: "2026-09-28T11:30:59+00:00",
              sets: [set(1, 8, 50)],
            },
            {
              workout_id: 2,
              position: 4,
              started_at: "2026-09-28T11:30:59+00:00",
              sets: [set(1, 8, 55)],
            },
            {
              workout_id: 1,
              position: 1,
              started_at: "2026-07-09T10:47:23+00:00",
              sets: [set(1, 10, 40)],
            },
          ],
        },
      },
    });
    await go("#/exercises/45");
    render(<App />);

    const chart = await screen.findByRole("img", { name: "Heaviest per session" });
    expect(text([...chart.querySelectorAll("circle title")])).toEqual([
      "9 Jul: 40 kg",
      "29 Sept: 50 kg",
      "29 Sept: 55 kg",
    ]);
  });

  it("shows timed exercises in seconds", async () => {
    standardApi();
    await go("#/exercises/23");
    render(<App />);

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Dead Hang");
    expect(screen.getByRole("button", { name: "Longest" })).toBeInTheDocument();
    expect(screen.getByText("Log this exercise twice to see a trend.")).toBeInTheDocument();
    expect(text([...document.querySelectorAll(".records .tile")])).toEqual(["50 sLongest"]);
  });

  it("shows a dash for records that do not exist yet", async () => {
    mockFetch({
      "/api/exercises/45/history": {
        body: {
          exercise: { ...PULLDOWN, equipment: null, workouts: 0 },
          carried_kg: 0,
          sessions: [],
        },
      },
    });
    await go("#/exercises/45");
    render(<App />);

    expect(await screen.findByText("0 workouts")).toBeInTheDocument();
    expect(text([...document.querySelectorAll(".records .tile strong")])).toEqual([
      "–",
      "–",
      "0 kg",
      "–",
    ]);
  });
});

describe("Navigation", () => {
  it("marks the current tab", async () => {
    standardApi();
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Sections" });
    const current = (): (string | null)[] =>
      text(
        within(nav)
          .getAllByRole("link")
          .filter((l) => l.getAttribute("aria-current") === "page"),
      );
    expect(current()).toEqual(["◉Home"]);

    await go("#/workouts/2");
    expect(current()).toEqual(["☰History"]);

    await go("#/exercises/45");
    expect(current()).toEqual(["✦Exercises"]);

    await go("#/history");
    expect(current()).toEqual(["☰History"]);

    await go("#/exercises");
    expect(current()).toEqual(["✦Exercises"]);
  });
});
