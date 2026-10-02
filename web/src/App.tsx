import type { ReactElement } from "react";

import { SyncBanner } from "./outbox/Sync";
import { href, useRoute } from "./router";
import type { FixedRouteName, Route } from "./router";
import { Coach } from "./screens/Coach";
import { ExerciseDetail } from "./screens/ExerciseDetail";
import { Exercises } from "./screens/Exercises";
import { History, WorkoutDetail } from "./screens/History";
import { Home } from "./screens/Home";
import { Inbox } from "./screens/Inbox";
import { Log } from "./screens/Log";
import { Picker } from "./screens/Picker";
import { Program } from "./screens/Program";
import { Settings } from "./screens/Settings";
import { Today } from "./screens/Today";

const SCREENS: Record<FixedRouteName, () => ReactElement> = {
  home: Home,
  history: History,
  exercises: Exercises,
  log: Log,
  pick: Picker,
  settings: Settings,
  coach: Coach,
  program: Program,
  today: Today,
  inbox: Inbox,
};

function Screen({ route }: { route: Route }): ReactElement {
  if (route.name === "workout") {
    return <WorkoutDetail key={route.id} id={route.id} />;
  }
  if (route.name === "exercise") {
    return <ExerciseDetail key={route.id} id={route.id} />;
  }
  const Fixed = SCREENS[route.name];
  return <Fixed />;
}

type Tab = "home" | "program" | "history" | "exercises" | "coach";

const TABS: { tab: Tab; route: Route; icon: string; label: string }[] = [
  { tab: "home", route: { name: "home" }, icon: "◉", label: "Home" },
  { tab: "program", route: { name: "program" }, icon: "▦", label: "Program" },
  { tab: "history", route: { name: "history" }, icon: "☰", label: "History" },
  { tab: "exercises", route: { name: "exercises" }, icon: "✦", label: "Exercises" },
  { tab: "coach", route: { name: "coach" }, icon: "✎", label: "Coach" },
];

const TAB_OF: Record<Route["name"], Tab> = {
  home: "home",
  log: "home",
  pick: "home",
  settings: "home",
  history: "history",
  workout: "history",
  exercises: "exercises",
  exercise: "exercises",
  coach: "coach",
  program: "program",
  today: "home",
  inbox: "home",
};

export function App(): ReactElement {
  const route = useRoute();
  const current = TAB_OF[route.name];
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
