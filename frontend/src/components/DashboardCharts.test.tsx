// @vitest-environment jsdom
// Renders the dashboard charts with sample figures (no server needed).
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { DayActivity, RegionHeadcount } from "../api/types";
import { I18nProvider } from "../i18n";
import { ActivityChart, RegionChart } from "./DashboardCharts";

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
