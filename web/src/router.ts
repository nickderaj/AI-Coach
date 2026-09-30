import { useSyncExternalStore } from "react";

export type Route =
  | { name: "workouts" }
  | { name: "workout"; id: number }
  | { name: "exercises" }
  | { name: "exercise"; id: number };

const PATTERNS: [RegExp, (id: number) => Route][] = [
  [/^#\/workouts\/(\d+)$/, (id): Route => ({ name: "workout", id })],
  [/^#\/exercises\/(\d+)$/, (id): Route => ({ name: "exercise", id })],
];

/**
 * Hash-based routes, so the server only ever serves index.html and assets.
 *
 * @internal Exported for tests; the app only uses it through `useRoute`.
 */
export function parseRoute(hash: string): Route {
  if (hash === "#/exercises") {
    return { name: "exercises" };
  }
  for (const [pattern, build] of PATTERNS) {
    const match = pattern.exec(hash);
    if (match?.[1] !== undefined) {
      return build(Number(match[1]));
    }
  }
  return { name: "workouts" };
}

export function href(route: Route): string {
  switch (route.name) {
    case "workouts":
      return "#/";
    case "exercises":
      return "#/exercises";
    case "workout":
      return `#/workouts/${String(route.id)}`;
    case "exercise":
      return `#/exercises/${String(route.id)}`;
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
  };
}

export function useRoute(): Route {
  return parseRoute(useSyncExternalStore(subscribe, () => window.location.hash));
}
