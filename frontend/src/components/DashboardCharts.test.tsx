// @vitest-environment jsdom
// Renders the dashboard charts with sample figures (no server needed).
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { DayActivity, RegionHeadcount } from "../api/types";
import { I18nProvider } from "../i18n";
import { ActivityChart, RangeSwitch, RegionChart } from "./DashboardCharts";

afterEach(cleanup);
const wrap = (ui: React.ReactElement) => render(<I18nProvider>{ui}</I18nProvider>);

const region = (code: string | null, total: number, active: number): RegionHeadcount =>
  ({ code, name_en: code ?? "", name_so: code ?? "", total, active });

describe("RegionChart", () => {
  it("sizes each bar against the largest region and splits active from not active", () => {
    const { container } = wrap(<RegionChart rows={[region("BARI", 10, 8), region("KARKAAR", 5, 5)]} />);
    const rows = container.querySelectorAll(".hb-row");
    expect(rows).toHaveLength(2);
    const seg = (row: Element, cls: string) => (row.querySelector(`.hb-seg.${cls}`) as HTMLElement).style.width;
    expect(seg(rows[0], "c1")).toBe("80%");
    expect(seg(rows[0], "c2")).toBe("20%");
    expect(seg(rows[1], "c1")).toBe("50%");
    expect(seg(rows[1], "c2")).toBe("0%");
    expect(within(rows[0] as HTMLElement).getByText("10")).toBeTruthy();
  });

  it("labels the row outside any region as Headquarters and keeps a text alternative for each bar", () => {
    const { container } = wrap(<RegionChart rows={[region("BARI", 4, 4), region(null, 2, 1)]} />);
    expect(screen.getByText("Headquarters")).toBeTruthy();
    expect(container.querySelectorAll(".hb-row .sr-only")).toHaveLength(2);
  });
});

describe("ActivityChart", () => {
  const days: DayActivity[] = [0, 1, 2, 3, 4, 5, 6].map((i) => ({ date: `2026-10-${String(24 + i).padStart(2, "0")}`, events: i === 2 ? 0 : i + 1, issues: i === 6 ? 2 : 0 }));

  it("draws one tick per day, an events column only when there were events, and a data table for screen readers", () => {
    const { container } = wrap(<ActivityChart days={days} />);
    expect(container.querySelector("svg[role='img']")).toBeTruthy();
    expect(container.querySelectorAll(".chart-tick")).toHaveLength(7);
    expect(container.querySelectorAll(".chart-col.c1")).toHaveLength(6);
    expect(container.querySelectorAll(".chart-col.c2")).toHaveLength(1);
    expect(container.querySelectorAll("table.sr-only tbody tr")).toHaveLength(7);
  });

  it("shows a plain message instead of an empty chart when nothing happened", () => {
    const { container } = wrap(<ActivityChart days={days.map((d) => ({ ...d, events: 0, issues: 0 }))} />);
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("No activity recorded in the last 7 days.")).toBeTruthy();
  });
});

describe("ActivityChart, wider views", () => {
  const month: DayActivity[] = Array.from({ length: 30 }, (_, i) => ({ date: `2026-10-${String(i + 1).padStart(2, "0")}`, events: i + 1, issues: i % 10 === 0 ? 1 : 0 }));

  it("draws a red issues column beside the events column and labels the week's counts", () => {
    const week: DayActivity[] = [0, 1, 2, 3, 4, 5, 6].map((i) => ({ date: `2026-10-${String(24 + i).padStart(2, "0")}`, events: 10 + i, issues: i === 6 ? 2 : 0 }));
    const { container } = wrap(<ActivityChart days={week} />);
    expect(container.querySelectorAll(".chart-val")).toHaveLength(7);
    expect(container.querySelectorAll(".chart-issue-val")).toHaveLength(1);
    expect(container.querySelector(".chart-tick.today")).toBeTruthy();
    expect(container.querySelectorAll(".swatch.issue")).toHaveLength(1);
  });

  it("over a month labels every fifth day and keeps all figures in the screen-reader table", () => {
    const { container } = wrap(<ActivityChart days={month} />);
    expect(container.querySelectorAll(".chart-col.c1")).toHaveLength(30);
    expect(container.querySelectorAll(".chart-col.c2")).toHaveLength(3);
    expect(container.querySelectorAll(".chart-tick")).toHaveLength(7); // days 1, 6, 11, 16, 21, 26 and today
    expect(container.querySelectorAll(".chart-val")).toHaveLength(0);
    expect(container.querySelectorAll("table.sr-only tbody tr")).toHaveLength(30);
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe("Activity, last 30 days");
  });

  it("uses the 30-day empty message over a month", () => {
    wrap(<ActivityChart days={month.map((d) => ({ ...d, events: 0, issues: 0 }))} />);
    expect(screen.getByText("No activity recorded in the last 30 days.")).toBeTruthy();
  });
});

describe("RangeSwitch", () => {
  it("marks the chosen range and reports a change", () => {
    const seen: number[] = [];
    wrap(<RangeSwitch value={7} onChange={(d) => seen.push(d)} />);
    expect(screen.getByRole("button", { name: "7 days" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "30 days" }).getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "30 days" }));
    expect(seen).toEqual([30]);
  });
});

describe("ActivityChart on a phone", () => {
  const week: DayActivity[] = [0, 1, 2, 3, 4, 5, 6].map((i) => ({ date: `2026-10-${String(24 + i).padStart(2, "0")}`, events: 100 + i, issues: i === 6 ? 2 : 0 }));
  const original = window.matchMedia;
  afterEach(() => { window.matchMedia = original; });

  it("uses the narrow drawing and puts the issue count under the date instead of beside the event count", () => {
    window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
    const { container } = wrap(<ActivityChart days={week} />);
    expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 340 210");
    expect(container.querySelectorAll(".chart-val")).toHaveLength(7);
    const issue = container.querySelector(".chart-issue-val");
    expect(issue?.textContent).toBe("2");
    expect(Number(issue?.getAttribute("y"))).toBeGreaterThan(Number(container.querySelector(".chart-tick")?.getAttribute("y")));
  });
});
