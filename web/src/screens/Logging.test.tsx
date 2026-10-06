import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { addBlock, addSet, newDraft, updateSet } from "../log/draft";
import type { Draft, DraftExercise } from "../log/draft";
import { App } from "../App";
import { DraftContext } from "../log/context";
import { draftStore } from "../log/store";
import { createOutbox } from "../outbox/outbox";
import { OutboxContext } from "../outbox/Sync";
import { outboxStore } from "../outbox/store";
import { renderLogging, routeFetch, writes } from "../test/logging";
import type * as RestAudioModule from "../restAudio";

const restAudio = vi.hoisted(() => ({
  shift: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
}));

vi.mock("../restAudio", async (importOriginal) => ({
  ...(await importOriginal<typeof RestAudioModule>()),
  shiftRestAudio: restAudio.shift,
  startRestAudio: restAudio.start,
  stopRestAudio: restAudio.stop,
}));

// Tests run in Pacific/Auckland (UTC+13): 07:30Z is 20:30 local.
const NOW = new Date("2026-09-30T08:00:00Z");
const STARTED = new Date("2026-09-30T07:30:00Z");

const PULLDOWN = {
  id: 45,
  name: "Lat Pulldown",
  equipment: "cable",
  muscle_groups: "back",
  measure: "reps",
  workouts: 7,
  last_done: "2026-09-28T11:30:59+00:00",
  best_load_kg: 60,
};
const HANG = {
  ...PULLDOWN,
  id: 23,
  name: "Dead Hang",
  equipment: "bodyweight",
  measure: "seconds",
  last_done: "2026-09-29T11:30:59+00:00",
  best_load_kg: null,
};
const ARNOLD = {
  ...PULLDOWN,
  id: 99,
  name: "Arnold Press",
  equipment: null,
  workouts: 0,
  last_done: null,
};
const EXERCISES = [ARNOLD, PULLDOWN, HANG];

const BENCH: DraftExercise = { id: 7, name: "Bench Press", measure: "reps", equipment: "barbell" };

/** A workout with Bench Press: set 1 prefilled at 8 × 60 kg. */
function benchDraft(): Draft {
  return addBlock(newDraft("w1", STARTED), { block: "b", set: "s1" }, BENCH, [
    { reps: 8, load_kg: 60, duration_s: null },
  ]);
}

/** The draft with set 1 of Bench Press logged as 8 × 60 kg. */
function logged(draft: Draft): Draft {
  return updateSet(draft, "b", "s1", { logged: { kg: "60", reps: "8", seconds: "", rpe: "" } });
}

async function go(hash: string): Promise<void> {
  await act(async () => {
    window.location.hash = hash;
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  restAudio.shift.mockClear();
  restAudio.start.mockClear();
  restAudio.stop.mockClear();
});

afterEach(() => {
  vi.useRealTimers();
  window.location.hash = "";
  localStorage.clear();
});

describe("Home", () => {
  beforeEach(() => {
    routeFetch({
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": { body: null },
    });
  });

  it("starts a workout and goes to pick the first exercise", async () => {
    const { outbox, drafts } = renderLogging();

    fireEvent.click(await screen.findByRole("button", { name: "Start workout" }));

    const draft = drafts.get();
    expect(draft).toMatchObject({ started_at: NOW.toISOString(), blocks: [] });
    expect(writes(outbox)).toEqual([
      [`PUT /api/workouts/${draft?.id ?? ""}`, { started_at: NOW.toISOString() }],
    ]);
    expect(window.location.hash).toBe("#/log/add");
  });

  it("offers to resume the workout in progress", async () => {
    renderLogging(logged(benchDraft()));

    const resume = await screen.findByRole("link", { name: /Workout in progress/ });
    expect(resume).toHaveTextContent("Started 20:30 · 1 set logged");
    expect(resume).toHaveAttribute("href", "#/log");
    expect(screen.queryByRole("button", { name: "Start workout" })).not.toBeInTheDocument();
  });

  it("picks up a workout left unfinished on the server", async () => {
    routeFetch({
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": {
        body: {
          id: 3,
          started_at: "2026-09-29T07:00:00+00:00",
          ended_at: null,
          notes: null,
          client_id: "w9",
          exercises: [],
        },
      },
    });
    const { drafts } = renderLogging();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Resume the unfinished workout from Tue 29 Sept, 20:00",
      }),
    );

    expect(drafts.get()).toMatchObject({ id: "w9", started_at: "2026-09-29T07:00:00+00:00" });
    expect(window.location.hash).toBe("#/log");
  });

  it("does not offer workouts imported without a client id", async () => {
    routeFetch({
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": {
        body: {
          id: 3,
          started_at: "2026-09-29T07:00:00+00:00",
          ended_at: null,
          notes: null,
          client_id: null,
          exercises: [],
        },
      },
    });
    renderLogging();

    await screen.findByText("No workouts yet.");
    expect(screen.queryByRole("button", { name: /Resume/ })).not.toBeInTheDocument();
  });
});

describe("Picker", () => {
  it("lists recent exercises first and adds one with last time's sets", async () => {
    routeFetch({
      "GET /api/exercises": { body: EXERCISES },
      "GET /api/exercises/45/history": {
        body: {
          exercise: PULLDOWN,
          carried_kg: 0,
          sessions: [
            {
              workout_id: 2,
              position: 1,
              started_at: "2026-09-28T11:30:59+00:00",
              sets: [
                {
                  set_number: 1,
                  reps: 10,
                  load_kg: 55,
                  duration_s: null,
                  rpe: null,
                  notes: null,
                  client_id: null,
                },
              ],
            },
          ],
        },
      },
    });
    await go("#/log/add");
    const { drafts } = renderLogging(newDraft("w1", STARTED));

    const choices = await screen.findAllByRole("button", { name: /workouts?/ });
    expect(choices.map((choice) => within(choice).getByRole("strong").textContent)).toEqual([
      "Dead Hang",
      "Lat Pulldown",
      "Arnold Press",
    ]);
    fireEvent.change(screen.getByLabelText("Search exercises"), { target: { value: "pull" } });
    fireEvent.click(screen.getByRole("button", { name: /Lat Pulldown/ }));

    await waitFor(() => {
      expect(window.location.hash).toBe("#/log");
    });
    expect(drafts.get()?.blocks).toEqual([
      {
        key: expect.any(String) as string,
        exercise: { id: 45, name: "Lat Pulldown", measure: "reps", equipment: "cable" },
        previous: [{ reps: 10, load_kg: 55, duration_s: null }],
        sets: [
          {
            id: expect.any(String) as string,
            kg: "55",
            reps: "10",
            seconds: "",
            rpe: "",
            logged: null,
          },
        ],
        slot_id: null,
        plan: null,
      },
    ]);
  });

  it("adds an exercise once however fast it is tapped", async () => {
    routeFetch({ "GET /api/exercises": { body: EXERCISES } });
    await go("#/log/add");
    const { drafts } = renderLogging(newDraft("w1", STARTED));

    const choice = await screen.findByRole("button", { name: /Arnold Press/ });
    fireEvent.click(choice);
    fireEvent.click(choice);

    await waitFor(() => {
      expect(window.location.hash).toBe("#/log");
    });
    expect(drafts.get()?.blocks).toHaveLength(1);
  });

  it("adds an exercise without last time when its history cannot be loaded", async () => {
    routeFetch({ "GET /api/exercises": { body: EXERCISES } });
    await go("#/log/add");
    const { drafts } = renderLogging(newDraft("w1", STARTED));

    fireEvent.click(await screen.findByRole("button", { name: /Arnold Press/ }));

    await waitFor(() => {
      expect(drafts.get()?.blocks[0]?.previous).toEqual([]);
    });
  });

  it("creates a new exercise and adds it", async () => {
    const fetchMock = routeFetch({
      "GET /api/exercises": { body: EXERCISES },
      "POST /api/exercises": {
        status: 201,
        body: { ...HANG, id: 60, name: "L-Sit", workouts: 0, last_done: null },
      },
    });
    await go("#/log/add");
    const { drafts } = renderLogging(newDraft("w1", STARTED));
    fireEvent.change(await screen.findByLabelText("Search exercises"), {
      target: { value: " L-Sit " },
    });

    fireEvent.click(screen.getByRole("button", { name: "+ New exercise" }));
    const form = screen.getByRole("form", { name: "New exercise" });
    expect(within(form).getByLabelText("Name")).toHaveValue("L-Sit");
    fireEvent.change(within(form).getByLabelText("Equipment"), { target: { value: "bodyweight" } });
    fireEvent.click(within(form).getByLabelText("Timed (a hold, logged in seconds)"));
    fireEvent.click(within(form).getByRole("button", { name: "Add exercise" }));

    await waitFor(() => {
      expect(drafts.get()?.blocks[0]?.exercise).toEqual({
        id: 60,
        name: "L-Sit",
        measure: "seconds",
        equipment: "bodyweight",
      });
    });
    const [, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "POST") ?? [];
    expect(JSON.parse(init?.body as string)).toEqual({
      name: "L-Sit",
      equipment: "bodyweight",
      measure: "seconds",
      allow_similar: false,
    });
  });

  it("offers the exercises a new one looks like, or adds it anyway", async () => {
    const fetchMock = routeFetch({
      "GET /api/exercises": { body: EXERCISES },
      "POST /api/exercises": {
        status: 409,
        body: {
          detail: {
            reason: "similar",
            matches: [{ id: 45, name: "Lat Pulldown", equipment: "cable" }],
          },
        },
      },
    });
    await go("#/log/add");
    const { drafts } = renderLogging(newDraft("w1", STARTED));
    fireEvent.click(await screen.findByRole("button", { name: "+ New exercise" }));
    const form = screen.getByRole("form", { name: "New exercise" });
    const submit = within(form).getByRole("button", { name: "Add exercise" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Lat Pull Down" } });
    expect(submit).toBeDisabled(); // equipment is required
    fireEvent.change(within(form).getByLabelText("Equipment"), { target: { value: "cable" } });
    fireEvent.click(submit);

    const alert = await within(form).findByRole("alert");
    expect(alert).toHaveTextContent("That looks like an exercise you already have.");
    fireEvent.click(within(alert).getByRole("button", { name: "No, add “Lat Pull Down”" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(2);
    });
    const [, second] = fetchMock.mock.calls.filter(([, i]) => i?.method === "POST")[1] ?? [];
    expect(JSON.parse(second?.body as string)).toMatchObject({ allow_similar: true });

    fireEvent.click(await within(form).findByRole("button", { name: "Use Lat Pulldown" }));

    await waitFor(() => {
      expect(drafts.get()?.blocks[0]?.exercise).toEqual({
        id: 45,
        name: "Lat Pulldown",
        measure: "reps",
        equipment: "cable",
      });
    });
  });

  it("points at the existing exercise when the name is taken", async () => {
    routeFetch({
      "GET /api/exercises": { body: EXERCISES },
      "POST /api/exercises": {
        status: 409,
        body: {
          detail: {
            reason: "exists",
            matches: [{ id: 77, name: "Plank", equipment: "bodyweight" }],
          },
        },
      },
    });
    await go("#/log/add");
    const { drafts } = renderLogging(newDraft("w1", STARTED));
    fireEvent.click(await screen.findByRole("button", { name: "+ New exercise" }));
    const form = screen.getByRole("form", { name: "New exercise" });
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "plank" } });
    fireEvent.change(within(form).getByLabelText("Equipment"), { target: { value: "bodyweight" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add exercise" }));

    const alert = await within(form).findByRole("alert");
    expect(alert).toHaveTextContent("That exercise is already in your list.");
    expect(within(alert).queryByRole("button", { name: /No, add/ })).not.toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("Equipment"), { target: { value: "band" } });
    expect(within(form).queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Add exercise" }));
    fireEvent.click(await within(form).findByRole("button", { name: "Use Plank" }));

    // Not in the loaded list (added elsewhere since), so it takes the form's measure.
    await waitFor(() => {
      expect(drafts.get()?.blocks[0]?.exercise).toEqual({
        id: 77,
        name: "Plank",
        equipment: "bodyweight",
        measure: "reps",
      });
    });
  });

  it("posts a new exercise once however fast the form is submitted", async () => {
    const fetchMock = routeFetch({
      "GET /api/exercises": { body: EXERCISES },
      "POST /api/exercises": {
        status: 201,
        body: { ...ARNOLD, id: 61, name: "Plank" },
      },
    });
    await go("#/log/add");
    const { drafts } = renderLogging(newDraft("w1", STARTED));
    fireEvent.click(await screen.findByRole("button", { name: "+ New exercise" }));
    const form = screen.getByRole("form", { name: "New exercise" });
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Plank" } });
    fireEvent.change(within(form).getByLabelText("Equipment"), { target: { value: "bodyweight" } });

    fireEvent.submit(form);
    fireEvent.submit(form);

    await waitFor(() => {
      expect(drafts.get()?.blocks).toHaveLength(1);
    });
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("says a new exercise needs a connection", async () => {
    routeFetch({
      "GET /api/exercises": { body: EXERCISES },
      "POST /api/exercises": new TypeError("offline"),
    });
    await go("#/log/add");
    renderLogging(newDraft("w1", STARTED));
    fireEvent.click(await screen.findByRole("button", { name: "+ New exercise" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Plank" } });
    fireEvent.change(screen.getByLabelText("Equipment"), { target: { value: "bodyweight" } });
    fireEvent.click(screen.getByRole("button", { name: "Add exercise" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Adding a new exercise needs a connection",
    );
  });

  it("asks for equipment, with bodyweight for none, before posting", async () => {
    const fetchMock = routeFetch({ "GET /api/exercises": { body: EXERCISES } });
    await go("#/log/add");
    renderLogging(newDraft("w1", STARTED));
    fireEvent.click(await screen.findByRole("button", { name: "+ New exercise" }));
    const form = screen.getByRole("form", { name: "New exercise" });
    const equipment = within(form).getByLabelText("Equipment");
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Plank" } });

    expect(equipment).toHaveValue("");
    expect(
      within(equipment)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "Choose…",
      "barbell",
      "dumbbell",
      "kettlebell",
      "cable",
      "machine",
      "bodyweight",
      "ez bar",
      "band",
      "other",
    ]);
    expect(within(equipment).getByRole("option", { name: "Choose…" })).toBeDisabled();
    fireEvent.submit(form); // Enter in the name field
    await Promise.resolve();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  });

  it.each(["#/log", "#/log/add"])("%s says there is no workout in progress", async (hash) => {
    await go(hash);
    renderLogging();

    expect(screen.getByText("No workout in progress. Start one from Home.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "‹ Home" })).toHaveAttribute("href", "#/");
  });
});

describe("Log", () => {
  beforeEach(async () => {
    await go("#/log");
  });

  const table = (): HTMLElement => screen.getByRole("region", { name: "Bench Press" });

  it("shows the workout with last time next to each set", () => {
    renderLogging(addSet(benchDraft(), "b", "s2"));

    expect(document.querySelector(".log-head p")).toHaveTextContent(
      "Started 20:30 · 30:00 · 0 sets",
    );
    const rows = within(table()).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "SetPreviouskgRepsRPEDone",
      "18 × 60 kg✓",
      "2–✓",
    ]);
    expect(within(table()).getByLabelText("Set 2 kg")).toHaveValue("60");
    expect(screen.getByRole("link", { name: "+ Add exercise" })).toHaveAttribute(
      "href",
      "#/log/add",
    );
  });

  it("logs a set when it is ticked off and starts the rest timer", () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(NOW);
    const { outbox, drafts } = renderLogging(benchDraft());

    fireEvent.click(screen.getByRole("button", { name: "Set 1 done" }));

    expect(writes(outbox)).toEqual([
      [
        "PUT /api/sets/s1",
        {
          workout_client_id: "w1",
          exercise_id: 7,
          reps: 8,
          load_kg: 60,
          duration_s: null,
          rpe: null,
        },
      ],
    ]);
    expect(screen.getByRole("button", { name: "Set 1 done" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(drafts.get()?.restUntil).toBe(NOW.getTime() + 90_000);
    expect(restAudio.start).toHaveBeenCalledWith(90_000);
    const timer = screen.getByRole("timer", { name: "Rest" });
    expect(timer).toHaveTextContent("Rest 1:30");

    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(timer).toHaveTextContent("Rest 1:10");
    fireEvent.click(within(timer).getByRole("button", { name: "+15 s" }));
    expect(timer).toHaveTextContent("Rest 1:25");
    expect(restAudio.shift).toHaveBeenLastCalledWith(15_000);
    fireEvent.click(within(timer).getByRole("button", { name: "−15 s" }));
    expect(timer).toHaveTextContent("Rest 1:10");
    expect(restAudio.shift).toHaveBeenLastCalledWith(-15_000);
    fireEvent.click(within(timer).getByRole("button", { name: "Skip" }));
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
    expect(restAudio.stop).toHaveBeenCalledOnce();
  });

  it("will not tick off an incomplete set", () => {
    const { outbox } = renderLogging(benchDraft());
    fireEvent.change(within(table()).getByLabelText("Set 1 reps"), { target: { value: "" } });

    expect(screen.getByRole("button", { name: "Set 1 done" })).toBeDisabled();
    fireEvent.blur(within(table()).getByLabelText("Set 1 reps"));
    expect(outbox.send).not.toHaveBeenCalled();
  });

  it("caps an adjusted rest at the audio track's ten-minute limit", () => {
    const draft = { ...benchDraft(), restUntil: NOW.getTime() + 595_000 };
    const { drafts } = renderLogging(draft);
    const timer = screen.getByRole("timer", { name: "Rest" });

    fireEvent.click(within(timer).getByRole("button", { name: "+15 s" }));

    expect(drafts.get()?.restUntil).toBe(NOW.getTime() + 600_000);
    expect(timer).toHaveTextContent("Rest 10:00");
  });

  it("queues a correction to a logged set as it is typed", () => {
    const { outbox, drafts } = renderLogging(logged(benchDraft()));
    const reps = within(table()).getByLabelText("Set 1 reps");

    fireEvent.change(reps, { target: { value: "1" } });
    fireEvent.change(reps, { target: { value: "10" } });
    fireEvent.change(within(table()).getByLabelText("Set 1 kg"), { target: { value: "62.5" } });

    // No blur needed: all of it is already queued, the outbox keeping the latest.
    expect(writes(outbox)).toEqual([
      ["PUT /api/sets/s1", expect.objectContaining({ reps: 1, load_kg: 60 })],
      ["PUT /api/sets/s1", expect.objectContaining({ reps: 10, load_kg: 60 })],
      ["PUT /api/sets/s1", expect.objectContaining({ reps: 10, load_kg: 62.5 })],
    ]);
    expect(drafts.get()?.blocks[0]?.sets[0]?.logged).toEqual({
      kg: "62.5",
      reps: "10",
      seconds: "",
      rpe: "",
    });
  });

  it("keeps the corrected set if the app is closed before leaving the field", () => {
    const { outbox } = renderLogging(logged(benchDraft()));
    fireEvent.change(within(table()).getByLabelText("Set 1 reps"), { target: { value: "9" } });
    cleanup(); // iOS kills the app: no blur

    const reopened = draftStore(localStorage, window).get();

    expect(reopened?.blocks[0]?.sets[0]).toMatchObject({
      reps: "9",
      logged: { kg: "60", reps: "9", seconds: "", rpe: "" },
    });
    expect(writes(outbox)).toEqual([
      ["PUT /api/sets/s1", expect.objectContaining({ reps: 9, load_kg: 60 })],
    ]);
  });

  it("puts an unfinished correction back when leaving the field, sending nothing", () => {
    const { outbox, drafts } = renderLogging(logged(benchDraft()));
    const reps = within(table()).getByLabelText("Set 1 reps");

    fireEvent.change(reps, { target: { value: "" } });
    expect(screen.getByRole("button", { name: "Set 1 done" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.blur(reps);

    expect(reps).toHaveValue("8");
    expect(outbox.send).not.toHaveBeenCalled();
    expect(drafts.get()?.blocks[0]?.sets[0]?.logged).toEqual({
      kg: "60",
      reps: "8",
      seconds: "",
      rpe: "",
    });
  });

  it("takes a set back off when it is unticked", () => {
    const { outbox } = renderLogging(logged(benchDraft()));

    fireEvent.click(screen.getByRole("button", { name: "Set 1 done" }));

    expect(writes(outbox)).toEqual([["DELETE /api/sets/s1", null]]);
    expect(screen.getByRole("button", { name: "Set 1 done" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("adds and removes sets and exercises", () => {
    const { outbox, drafts } = renderLogging(benchDraft());

    expect(within(table()).queryByRole("button", { name: "− Remove set" })).not.toBeInTheDocument();
    fireEvent.click(within(table()).getByRole("button", { name: "+ Add set" }));
    expect(within(table()).getByLabelText("Set 2 reps")).toHaveValue("8");
    fireEvent.click(screen.getByRole("button", { name: "Set 2 done" }));
    fireEvent.click(within(table()).getByRole("button", { name: "− Remove set" }));

    expect(writes(outbox).map(([what]) => what)).toEqual([
      expect.stringMatching(/^PUT \/api\/sets\//),
      expect.stringMatching(/^DELETE \/api\/sets\//),
    ]);
    fireEvent.click(within(table()).getByRole("button", { name: "+ Add set" }));
    fireEvent.click(within(table()).getByRole("button", { name: "− Remove set" }));
    expect(outbox.send).toHaveBeenCalledTimes(2);

    fireEvent.click(within(table()).getByRole("button", { name: "Remove exercise" }));
    expect(drafts.get()?.blocks).toEqual([]);
  });

  it("keeps an exercise with logged sets", () => {
    renderLogging(logged(benchDraft()));

    expect(
      within(table()).queryByRole("button", { name: "Remove exercise" }),
    ).not.toBeInTheDocument();
  });

  it("logs timed exercises in seconds", () => {
    const hang: DraftExercise = { id: 23, name: "Dead Hang", measure: "seconds", equipment: null };
    const draft = addBlock(newDraft("w1", STARTED), { block: "h", set: "h1" }, hang, [
      { reps: null, load_kg: null, duration_s: 50 },
    ]);
    const { outbox } = renderLogging(draft);
    const card = screen.getByRole("region", { name: "Dead Hang" });

    expect(within(card).getByRole("columnheader", { name: "Secs" })).toBeInTheDocument();
    expect(within(card).getByText("50 s")).toBeInTheDocument();
    fireEvent.change(within(card).getByLabelText("Set 1 seconds"), { target: { value: "55" } });
    fireEvent.click(within(card).getByRole("button", { name: "Set 1 done" }));

    expect(writes(outbox)).toEqual([
      [
        "PUT /api/sets/h1",
        {
          workout_client_id: "w1",
          exercise_id: 23,
          reps: null,
          load_kg: null,
          duration_s: 55,
          rpe: null,
        },
      ],
    ]);
  });

  it("will not finish an empty workout", () => {
    const { outbox } = renderLogging(benchDraft());

    fireEvent.click(screen.getByRole("button", { name: "Finish" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Nothing is logged yet.");
    expect(outbox.send).not.toHaveBeenCalled();
  });

  it("finishes the workout and goes home", async () => {
    routeFetch({ "GET /api/workouts?limit=500": { body: [] } });
    const { outbox, drafts } = renderLogging(logged(benchDraft()));

    fireEvent.click(screen.getByRole("button", { name: "Finish" }));

    await waitFor(() => {
      expect(window.location.hash).toBe("#/");
    });
    expect(writes(outbox)).toEqual([
      ["PUT /api/workouts/w1", { started_at: STARTED.toISOString(), ended_at: NOW.toISOString() }],
    ]);
    expect(drafts.get()).toBeNull();
  });

  it("asks before discarding the workout", async () => {
    routeFetch({ "GET /api/workouts?limit=500": { body: [] } });
    const { outbox, drafts } = renderLogging(logged(benchDraft()));

    fireEvent.click(screen.getByRole("button", { name: "Discard workout" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Discard this workout and its 1 logged set?",
    );
    fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Discard workout" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));

    await waitFor(() => {
      expect(window.location.hash).toBe("#/");
    });
    expect(writes(outbox)).toEqual([["DELETE /api/workouts/w1", null]]);
    expect(drafts.get()).toBeNull();
  });
});

describe("QuickLog", () => {
  const history = (exercise: { id: number }): Record<string, { body: unknown }> => ({
    [`GET /api/exercises/${String(exercise.id)}/history`]: {
      body: { exercise, carried_kg: 0, sessions: [] },
    },
  });

  it("logs one set as a workout of its own", async () => {
    routeFetch(history(PULLDOWN));
    await go("#/exercises/45");
    const { outbox } = renderLogging();

    const form = await screen.findByRole("form", { name: "Log one set" });
    const log = within(form).getByRole("button", { name: "Log" });
    expect(log).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("kg"), { target: { value: "60" } });
    fireEvent.change(within(form).getByLabelText("reps"), { target: { value: "8" } });
    fireEvent.click(log);

    expect(await within(form).findByRole("status")).toHaveTextContent("Logged 8 × 60 kg.");
    const [workout, set] = outbox.send.mock.calls.map(([write]) => write);
    expect(workout).toMatchObject({
      method: "PUT",
      label: "One-off Lat Pulldown",
      body: { started_at: NOW.toISOString(), ended_at: NOW.toISOString() },
    });
    expect(set).toMatchObject({
      method: "PUT",
      body: { exercise_id: 45, reps: 8, load_kg: 60, duration_s: null },
    });
    expect(set?.body).toMatchObject({ workout_client_id: workout?.path.split("/").at(-1) });
    expect(within(form).getByLabelText("reps")).toHaveValue("");
  });

  it("logs one workout however fast the button is tapped", async () => {
    routeFetch(history(PULLDOWN));
    await go("#/exercises/45");
    const { outbox } = renderLogging();
    let arrive: () => void = () => undefined;
    outbox.send.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          arrive = resolve;
        }),
    );

    const form = await screen.findByRole("form", { name: "Log one set" });
    fireEvent.change(within(form).getByLabelText("reps"), { target: { value: "8" } });
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(within(form).getByRole("button", { name: "Log" })).toBeDisabled();
    await act(async () => {
      arrive();
      await Promise.resolve();
    });

    expect(await within(form).findByRole("status")).toHaveTextContent("Logged 8 reps.");
    const paths = outbox.send.mock.calls.map(([write]) => write.path);
    expect(paths).toHaveLength(2);
    expect(paths[0]).toMatch(/^\/api\/workouts\//);
    expect(paths[1]).toMatch(/^\/api\/sets\//);
    expect(within(form).getByRole("button", { name: "Log" })).toBeDisabled(); // empty again
  });

  it("logs a hold in seconds", async () => {
    routeFetch(history(HANG));
    await go("#/exercises/23");
    const { outbox } = renderLogging();

    const form = await screen.findByRole("form", { name: "Log one set" });
    fireEvent.change(within(form).getByLabelText("seconds"), { target: { value: "45" } });
    fireEvent.submit(form);

    expect(await within(form).findByRole("status")).toHaveTextContent("Logged 45 s.");
    expect(outbox.send.mock.calls[1]?.[0].body).toMatchObject({ duration_s: 45, reps: null });
  });

  it("ignores an incomplete set", async () => {
    routeFetch(history(PULLDOWN));
    await go("#/exercises/45");
    const { outbox } = renderLogging();

    fireEvent.submit(await screen.findByRole("form", { name: "Log one set" }));

    expect(outbox.send).not.toHaveBeenCalled();
  });

  it("points at the workout in progress instead", async () => {
    routeFetch(history(PULLDOWN));
    await go("#/exercises/45");
    renderLogging(benchDraft());

    expect(await screen.findByRole("link", { name: "log sets there" })).toHaveAttribute(
      "href",
      "#/log",
    );
    expect(screen.queryByRole("form", { name: "Log one set" })).not.toBeInTheDocument();
  });
});

describe("Settings", () => {
  it("speaks the rest countdown until it is turned off", async () => {
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: 65 } } });
    await go("#/settings");
    renderLogging();

    const section = screen.getByRole("region", { name: "Rest countdown" });
    const toggle = within(section).getByRole("switch", { name: "Spoken countdown" });
    expect(toggle).toBeChecked();
    expect(section).toHaveTextContent("over any music you are playing");

    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    cleanup();
    renderLogging();

    expect(
      within(screen.getByRole("region", { name: "Rest countdown" })).getByRole("switch"),
    ).not.toBeChecked();
  });

  it("only enables the background rest timer after an explicit choice", async () => {
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: 65 } } });
    await go("#/settings");
    renderLogging();

    const section = screen.getByRole("region", { name: "Background rest timer" });
    const toggle = within(section).getByRole("switch", { name: "Show rests outside Coach" });
    expect(toggle).not.toBeChecked();
    expect(section).toHaveTextContent("may pause music from another app");

    fireEvent.click(toggle);
    expect(toggle).toBeChecked();
    cleanup();
    renderLogging();

    expect(
      within(screen.getByRole("region", { name: "Background rest timer" })).getByRole("switch"),
    ).toBeChecked();
  });

  it("saves the body weight through the outbox", async () => {
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: 65 } } });
    await go("#/settings");
    const { outbox } = renderLogging();

    const form = await screen.findByRole("form", { name: "Body weight" });
    const kg = within(form).getByLabelText("kg");
    expect(kg).toHaveValue("65");
    fireEvent.change(kg, { target: { value: "64,5" } });
    fireEvent.submit(form);

    expect(await within(form).findByRole("status")).toHaveTextContent("Saved.");
    expect(writes(outbox)).toEqual([["PUT /api/profile", { bodyweight_kg: 64.5 }]]);
    fireEvent.change(kg, { target: { value: "" } });
    expect(within(form).queryByRole("status")).not.toBeInTheDocument();
    fireEvent.submit(form);
    await within(form).findByRole("status");
    expect(writes(outbox).at(-1)).toEqual(["PUT /api/profile", { bodyweight_kg: null }]);
    expect(screen.getByRole("link", { name: "‹ Home" })).toHaveAttribute("href", "#/");
  });

  it("keeps a change saved offline when Settings is opened again", async () => {
    // Offline: the cached profile still says 65, and the save cannot be sent.
    routeFetch({
      "GET /api/profile": { body: { bodyweight_kg: 65 } },
      "PUT /api/profile": new TypeError("offline"),
    });
    await go("#/settings");
    const store = outboxStore(new IDBFactory());
    const outbox = createOutbox(store, (task) => task());
    const stop = outbox.start();
    const open = (): void => {
      render(
        <OutboxContext value={outbox}>
          <DraftContext value={draftStore(localStorage, window)}>
            <App />
          </DraftContext>
        </OutboxContext>,
      );
    };

    open();
    const form = await screen.findByRole("form", { name: "Body weight" });
    fireEvent.change(within(form).getByLabelText("kg"), { target: { value: "70" } });
    fireEvent.submit(form);
    expect(await within(form).findByRole("status")).toHaveTextContent("Saved.");
    cleanup();

    open(); // Settings again, still offline
    const again = await screen.findByRole("form", { name: "Body weight" });
    expect(within(again).getByLabelText("kg")).toHaveValue("70");
    fireEvent.submit(again);
    await within(again).findByRole("status");

    expect((await store.queued("/api/profile"))?.body).toEqual({ bodyweight_kg: 70 });
    stop();
  });

  it("looks for a queued change once, not on every render", async () => {
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: 65 } } });
    await go("#/settings");
    const { outbox } = renderLogging();

    const form = await screen.findByRole("form", { name: "Body weight" });
    fireEvent.change(within(form).getByLabelText("kg"), { target: { value: "66" } });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(outbox.queued).toHaveBeenCalledOnce();
    expect(outbox.queued).toHaveBeenCalledWith("/api/profile");
  });

  it("says when the change could not be saved on the phone", async () => {
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: 65 } } });
    await go("#/settings");
    const { outbox } = renderLogging();
    outbox.send.mockRejectedValueOnce(new Error("quota exceeded"));

    const form = await screen.findByRole("form", { name: "Body weight" });
    fireEvent.submit(form);

    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Could not save on this phone.",
    );
    expect(within(form).queryByRole("status")).not.toBeInTheDocument();
  });

  it("cannot save where nothing can be queued", async () => {
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: 65 } } });
    await go("#/settings");
    render(<App />);

    const form = await screen.findByRole("form", { name: "Body weight" });
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.submit(form); // e.g. Enter in the field
    expect(within(form).queryByRole("status")).not.toBeInTheDocument();
  });

  it.each(["0", "abc", "501"])("will not save %s kg", async (typed) => {
    routeFetch({ "GET /api/profile": { body: { bodyweight_kg: null } } });
    await go("#/settings");
    renderLogging();

    const form = await screen.findByRole("form", { name: "Body weight" });
    expect(within(form).getByLabelText("kg")).toHaveValue("");
    fireEvent.change(within(form).getByLabelText("kg"), { target: { value: typed } });

    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("is reached from Home", async () => {
    routeFetch({
      "GET /api/workouts?limit=500": { body: [] },
      "GET /api/workouts/current": { body: null },
    });
    renderLogging();

    expect(await screen.findByRole("link", { name: "Settings" })).toHaveAttribute(
      "href",
      "#/settings",
    );
  });
});
