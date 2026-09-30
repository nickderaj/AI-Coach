import type { ReactElement } from "react";

import { SyncBanner } from "./outbox/Sync";
import { href, useRoute } from "./router";
import type { Route } from "./router";
import { ExerciseDetail } from "./screens/ExerciseDetail";
import { Exercises } from "./screens/Exercises";
import { History, WorkoutDetail } from "./screens/History";
import { Home } from "./screens/Home";
import { Log } from "./screens/Log";
import { Picker } from "./screens/Picker";

function Screen({ route }: { route: Route }): ReactElement {
  switch (route.name) {
    case "home":
      return <Home />;
    case "history":
      return <History />;
    case "workout":
      return <WorkoutDetail key={route.id} id={route.id} />;
    case "exercises":
      return <Exercises />;
    case "exercise":
      return <ExerciseDetail key={route.id} id={route.id} />;
    case "log":
      return <Log />;
    case "pick":
      return <Picker />;
  }
}

type Tab = "home" | "history" | "exercises";

const TABS: { tab: Tab; route: Route; icon: string; label: string }[] = [
  { tab: "home", route: { name: "home" }, icon: "◉", label: "Home" },
  { tab: "history", route: { name: "history" }, icon: "☰", label: "History" },
  { tab: "exercises", route: { name: "exercises" }, icon: "✦", label: "Exercises" },
];

function tabOf(route: Route): Tab {
  switch (route.name) {
    case "home":
    case "log":
    case "pick":
      return "home";
    case "history":
    case "workout":
      return "history";
    case "exercises":
    case "exercise":
      return "exercises";
  }
}

export function App(): ReactElement {
  const route = useRoute();
  const current = tabOf(route);
  return (
    <div className="app">
      <main>
        <SyncBanner />
        <Screen route={route} />
      </main>
      <nav className="tabs" aria-label="Sections">
        {TABS.map(({ tab, route: target, icon, label }) => (
          <a key={tab} href={href(target)} aria-current={tab === current ? "page" : undefined}>
            <span aria-hidden="true">{icon}</span>
            {label}
          </a>
        ))}
      </nav>
    </div>
  );
}
