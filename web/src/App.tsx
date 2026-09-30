import type { ReactElement } from "react";

import { href, useRoute } from "./router";
import type { Route } from "./router";
import { ExerciseHistory, ExerciseList, WorkoutDetail, WorkoutList } from "./screens";

function Screen({ route }: { route: Route }): ReactElement {
  switch (route.name) {
    case "workouts":
      return <WorkoutList />;
    case "workout":
      return <WorkoutDetail key={route.id} id={route.id} />;
    case "exercises":
      return <ExerciseList />;
    case "exercise":
      return <ExerciseHistory key={route.id} id={route.id} />;
  }
}

function inSection(route: Route): "history" | "exercises" {
  return route.name === "exercises" || route.name === "exercise" ? "exercises" : "history";
}

export function App(): ReactElement {
  const route = useRoute();
  const section = inSection(route);
  return (
    <div className="app">
      <main>
        <Screen route={route} />
      </main>
      <nav className="tabs" aria-label="Sections">
        <a
          href={href({ name: "workouts" })}
          aria-current={section === "history" ? "page" : undefined}
        >
          History
        </a>
        <a
          href={href({ name: "exercises" })}
          aria-current={section === "exercises" ? "page" : undefined}
        >
          Exercises
        </a>
      </nav>
    </div>
  );
}
