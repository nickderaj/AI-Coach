import { act, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { href, navigate, parseRoute, useRoute } from "./router";
import type { Route } from "./router";

describe("parseRoute", () => {
  it.each<[string, Route]>([
    ["", { name: "home" }],
    ["#/", { name: "home" }],
    ["#/history", { name: "history" }],
    ["#/exercises", { name: "exercises" }],
    ["#/workouts/12", { name: "workout", id: 12 }],
    ["#/exercises/7", { name: "exercise", id: 7 }],
    ["#/log", { name: "log" }],
    ["#/log/add", { name: "pick" }],
    ["#/settings", { name: "settings" }],
    ["#/coach", { name: "coach" }],
    ["#/program", { name: "program" }],
    ["#/workouts/abc", { name: "home" }],
    ["#/exercises/7/extra", { name: "home" }],
    ["#/nonsense", { name: "home" }],
  ])("%s", (hash, route) => {
    expect(parseRoute(hash)).toEqual(route);
  });
});

describe("href", () => {
  it.each<[Route, string]>([
    [{ name: "home" }, "#/"],
    [{ name: "history" }, "#/history"],
    [{ name: "exercises" }, "#/exercises"],
    [{ name: "workout", id: 3 }, "#/workouts/3"],
    [{ name: "exercise", id: 9 }, "#/exercises/9"],
    [{ name: "log" }, "#/log"],
    [{ name: "pick" }, "#/log/add"],
    [{ name: "settings" }, "#/settings"],
    [{ name: "coach" }, "#/coach"],
    [{ name: "program" }, "#/program"],
  ])("round-trips %j", (route, hash) => {
    expect(href(route)).toBe(hash);
    expect(parseRoute(hash)).toEqual(route);
  });
});

function Probe(): ReactElement {
  return <output>{JSON.stringify(useRoute())}</output>;
}

describe("navigate", () => {
  afterEach(() => {
    window.location.hash = "";
  });

  it("follows the route's link", () => {
    navigate({ name: "pick" });

    expect(window.location.hash).toBe("#/log/add");
  });
});

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
