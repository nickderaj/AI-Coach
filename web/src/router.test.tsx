import { act, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { href, parseRoute, useRoute } from "./router";
import type { Route } from "./router";

describe("parseRoute", () => {
  it.each<[string, Route]>([
    ["", { name: "workouts" }],
    ["#/", { name: "workouts" }],
    ["#/exercises", { name: "exercises" }],
    ["#/workouts/12", { name: "workout", id: 12 }],
    ["#/exercises/7", { name: "exercise", id: 7 }],
    ["#/workouts/abc", { name: "workouts" }],
    ["#/exercises/7/extra", { name: "workouts" }],
    ["#/nonsense", { name: "workouts" }],
  ])("%s", (hash, route) => {
    expect(parseRoute(hash)).toEqual(route);
  });
});

describe("href", () => {
  it.each<[Route, string]>([
    [{ name: "workouts" }, "#/"],
    [{ name: "exercises" }, "#/exercises"],
    [{ name: "workout", id: 3 }, "#/workouts/3"],
    [{ name: "exercise", id: 9 }, "#/exercises/9"],
  ])("round-trips %j", (route, hash) => {
    expect(href(route)).toBe(hash);
    expect(parseRoute(hash)).toEqual(route);
  });
});

function Probe(): ReactElement {
  return <output>{JSON.stringify(useRoute())}</output>;
}

describe("useRoute", () => {
  afterEach(() => {
    window.location.hash = "";
  });

  it("follows hash changes", async () => {
    window.location.hash = "#/exercises";
    render(<Probe />);
    expect(screen.getByRole("status")).toHaveTextContent('{"name":"exercises"}');

    await act(async () => {
      window.location.hash = "#/workouts/5";
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.getByRole("status")).toHaveTextContent('{"name":"workout","id":5}');
  });
});
