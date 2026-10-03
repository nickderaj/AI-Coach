import type { ReactElement } from "react";

/** Small dependency-free SVG charts. Colours come from CSS variables in theme.css. */

const WIDTH = 320;
const HEIGHT = 140;
const PAD_X = 8;
const PAD_TOP = 18;
const PAD_BOTTOM = 22;

export interface Bar {
  label: string;
  value: number;
  highlight?: boolean;
}

export function BarChart({
  bars,
  title,
  format,
}: {
  bars: Bar[];
  title: string;
  format: (value: number) => string;
}): ReactElement {
  const top = Math.max(1, ...bars.map((bar) => bar.value));
  const slot = (WIDTH - PAD_X * 2) / Math.max(1, bars.length);
  const plot = HEIGHT - PAD_TOP - PAD_BOTTOM;
  return (
    <svg className="chart" viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`} role="img">
      <title>{title}</title>
      {bars.map((bar, index) => {
        const height = (bar.value / top) * plot;
        const x = PAD_X + index * slot + slot * 0.18;
        return (
          <g key={bar.label} className={bar.highlight === true ? "bar current" : "bar"}>
            <rect
              x={x}
              y={PAD_TOP + plot - height}
              width={slot * 0.64}
              height={Math.max(height, 2)}
              rx={1}
            >
              <title>{`${bar.label}: ${format(bar.value)}`}</title>
            </rect>
            <text x={x + slot * 0.32} y={HEIGHT - 6} textAnchor="middle" className="axis">
              {bar.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export interface Point {
  key: string;
  label: string;
  value: number;
}

export function LineChart({
  points,
  title,
  format,
}: {
  points: Point[];
  title: string;
  format: (value: number) => string;
}): ReactElement {
  if (points.length < 2) {
    return <p className="muted chart-empty">Log this exercise twice to see a trend.</p>;
  }
  const values = points.map((point) => point.value);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const plot = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const step = (WIDTH - PAD_X * 2 - 40) / (points.length - 1);
  const coords = points.map((point, index) => ({
    x: PAD_X + 40 + index * step,
    y: PAD_TOP + plot - ((point.value - low) / span) * plot,
    point,
  }));
  const first = points[0];
  const last = points[points.length - 1];
  return (
    <svg className="chart" viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`} role="img">
      <title>{title}</title>
      <text x={PAD_X} y={PAD_TOP + 4} className="axis">
        {format(high)}
      </text>
      <text x={PAD_X} y={PAD_TOP + plot} className="axis">
        {format(low)}
      </text>
      <polyline
        className="line"
        points={coords.map((c) => `${String(c.x)},${String(c.y)}`).join(" ")}
      />
      {coords.map((c) => (
        <circle key={c.point.key} className="dot" cx={c.x} cy={c.y} r={3.5}>
          <title>{`${c.point.label}: ${format(c.point.value)}`}</title>
        </circle>
      ))}
      <text x={PAD_X + 40} y={HEIGHT - 6} className="axis">
        {first?.label}
      </text>
      <text x={WIDTH - PAD_X} y={HEIGHT - 6} textAnchor="end" className="axis">
        {last?.label}
      </text>
    </svg>
  );
}
