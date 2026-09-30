import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BarChart, LineChart } from "./charts";

const kg = (value: number): string => `${String(value)} kg`;

describe("BarChart", () => {
  it("draws one labelled bar per value, scaled to the largest", () => {
    const { container } = render(
      <BarChart
        title="Volume"
        format={kg}
        bars={[
          { label: "a", value: 50 },
          { label: "b", value: 100, highlight: true },
          { label: "c", value: 0 },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: "Volume" })).toBeInTheDocument();
    const bars = [...container.querySelectorAll("g")];
    expect(bars.map((bar) => bar.getAttribute("class"))).toEqual(["bar", "bar current", "bar"]);
    const heights = [...container.querySelectorAll("rect")].map((rect) =>
      Number(rect.getAttribute("height")),
    );
    expect(heights).toEqual([50, 100, 2]); // a zero bar keeps a visible 2px sliver
    expect([...container.querySelectorAll("rect title")].map((t) => t.textContent)).toEqual([
      "a: 50 kg",
      "b: 100 kg",
      "c: 0 kg",
    ]);
  });

  it("copes with all-zero data", () => {
    const { container } = render(
      <BarChart title="Empty" format={kg} bars={[{ label: "a", value: 0 }]} />,
    );

    expect(container.querySelector("rect")?.getAttribute("height")).toBe("2");
  });
});

describe("LineChart", () => {
  const points = [
    { key: "1", label: "1 Sept", value: 60 },
    { key: "2", label: "8 Sept", value: 70 },
    { key: "3", label: "15 Sept", value: 65 },
  ];

  it("plots points between the lowest and highest values", () => {
    const { container } = render(<LineChart title="Heaviest" format={kg} points={points} />);

    expect(screen.getByRole("img", { name: "Heaviest" })).toBeInTheDocument();
    const texts = [...container.querySelectorAll("text")].map((t) => t.textContent);
    expect(texts).toEqual(["70 kg", "60 kg", "1 Sept", "15 Sept"]);
    const ys = [...container.querySelectorAll("circle")].map((c) => Number(c.getAttribute("cy")));
    expect(ys).toEqual([118, 18, 68]); // lowest at the bottom, highest at the top
    expect(container.querySelector("polyline")?.getAttribute("points")?.split(" ")).toHaveLength(3);
  });

  it("draws a flat line when every value is equal", () => {
    const flat = points.map((point) => ({ ...point, value: 50 }));
    const { container } = render(<LineChart title="Flat" format={kg} points={flat} />);

    const ys = [...container.querySelectorAll("circle")].map((c) => c.getAttribute("cy"));
    expect(new Set(ys).size).toBe(1);
  });

  it("asks for more data with fewer than two points", () => {
    render(<LineChart title="One" format={kg} points={points.slice(0, 1)} />);

    expect(screen.getByText("Log this exercise twice to see a trend.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
