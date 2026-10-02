import { useState } from "react";
import type { ReactElement } from "react";

import { inboxSchema, useApi, workoutListSchema } from "../api";
import type { WorkoutSummary } from "../api";
import { BarChart } from "../charts";
import { Load, StatTile, WorkoutCard } from "../components";
import { formatVolume, formatWhole, partOfDay } from "../format";
import { href } from "../router";
import { thisWeek, weekStreak, weeklyTotals } from "../stats";
import { StartCard } from "./StartCard";

const WEEKS = 8;
const WEEK_LABEL = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "numeric" });

function Dashboard({ workouts, now }: { workouts: WorkoutSummary[]; now: Date }): ReactElement {
  const weeks = weeklyTotals(workouts, WEEKS, now);
  const current = thisWeek(workouts, now);
  const streak = weekStreak(workouts, now);
  return (
    <>
      <div className="tiles">
        <StatTile color="mauve" value={String(current.workouts)} label="this week" />
        <StatTile
          color="peach"
          value={String(streak)}
          label={streak === 1 ? "week streak" : "weeks streak"}
        />
        <StatTile color="green" value={formatWhole(current.volume)} label="kg this week" />
      </div>
      <section className="card">
        <h2>Volume per week</h2>
        <BarChart
          title="Volume lifted per week, last 8 weeks"
          format={formatVolume}
          bars={weeks.map((week, index) => ({
            label: WEEK_LABEL.format(week.start),
            value: week.volume,
            highlight: index === weeks.length - 1,
          }))}
        />
      </section>
      <section>
        <h2>Recent workouts</h2>
        {workouts.length === 0 ? (
          <p className="muted">No workouts yet.</p>
        ) : (
          <ul className="list">
            {workouts.slice(0, 3).map((workout) => (
              <WorkoutCard key={workout.id} workout={workout} />
            ))}
          </ul>
        )}
        <p>
          <a className="back" href={href({ name: "history" })}>
            All workouts ›
          </a>
        </p>
      </section>
    </>
  );
}

/** The inbox, with how many notices are unread. */
function InboxLink(): ReactElement {
  const state = useApi("/api/inbox", inboxSchema);
  const unread = state.status === "ready" ? state.data.unread : 0;
  return (
    <a
      className="head-link"
      href={href({ name: "inbox" })}
      aria-label={unread === 0 ? "Inbox" : `Inbox, ${String(unread)} unread`}
    >
      ✉{unread === 0 ? null : <span className="badge">{String(unread)}</span>}
    </a>
  );
}

export function Home(): ReactElement {
  const state = useApi("/api/workouts?limit=500", workoutListSchema);
  const [now] = useState(() => new Date());
  return (
    <>
      <header className="page-head home-head">
        <span>
          <p className="muted">Good {partOfDay(now.toISOString()).toLowerCase()}</p>
          <h1>Your training</h1>
        </span>
        <span className="head-links">
          <InboxLink />
          <a className="head-link" href={href({ name: "settings" })} aria-label="Settings">
            ⚙
          </a>
        </span>
      </header>
      <StartCard />
      <Load state={state}>{(workouts) => <Dashboard workouts={workouts} now={now} />}</Load>
    </>
  );
}
