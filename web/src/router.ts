import { useSyncExternalStore } from "react";

export type Route =
  | { name: "home" }
  | { name: "history" }
  | { name: "workout"; id: number }
  | { name: "exercises" }
  | { name: "exercise"; id: number }
  | { name: "log" }
  | { name: "pick" };

const STATIC: Record<string, Route> = {
  "#/history": { name: "history" },
  "#/exercises": { name: "exercises" },
  "#/log": { name: "log" },
  "#/log/add": { name: "pick" },
};

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
  const fixed = STATIC[hash];
  if (fixed !== undefined) {
    return fixed;
  }
  for (const [pattern, build] of PATTERNS) {
    const match = pattern.exec(hash);
    if (match?.[1] !== undefined) {
      return build(Number(match[1]));
    }
  }
  return { name: "home" };
}

export function href(route: Route): string {
  switch (route.name) {
    case "home":
      return "#/";
    case "history":
      return "#/history";
    case "exercises":
      return "#/exercises";
    case "workout":
      return `#/workouts/${String(route.id)}`;
    case "exercise":
      return `#/exercises/${String(route.id)}`;
    case "log":
      return "#/log";
    case "pick":
      return "#/log/add";
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return (): void => {
    window.removeEventListener("hashchange", onChange);
  };
}

/** Go to `route`, as if a link to it had been followed. */
export function navigate(route: Route): void {
  window.location.hash = href(route);
}

export function useRoute(): Route {
  return parseRoute(useSyncExternalStore(subscribe, () => window.location.hash));
}
