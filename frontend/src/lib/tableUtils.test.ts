import { describe, expect, it } from "vitest";
import { clampWidth, MAX_COL, MIN_COL, nextSort, pageRange, pageWindow, sanitizePrefs, sortRows } from "./tableUtils";

describe("sortRows", () => {
  const rows = [{ n: "b", v: 2 }, { n: "a", v: 10 }, { n: "c", v: null }, { n: "d", v: 2 }];
  it("sorts numbers numerically, keeps ties stable, and puts empty values last in both directions", () => {
    expect(sortRows(rows, (r) => r.v, "asc").map((r) => r.n)).toEqual(["b", "d", "a", "c"]);
    expect(sortRows(rows, (r) => r.v, "desc").map((r) => r.n)).toEqual(["a", "b", "d", "c"]);
  });
  it("sorts text naturally and without touching the input", () => {
    const t = [{ s: "Unit 10" }, { s: "Unit 2" }];
    expect(sortRows(t, (r) => r.s, "asc").map((r) => r.s)).toEqual(["Unit 2", "Unit 10"]);
    expect(t[0].s).toBe("Unit 10");
  });
  it("leaves the order alone for a column without a sort key", () => {
    expect(sortRows(rows, null, "asc")).toEqual(rows);
  });
});

describe("nextSort", () => {
  it("cycles ascending, descending, off, and restarts on another column", () => {
    const a = nextSort(null, "x");
    expect(a).toEqual({ id: "x", dir: "asc" });
    const d = nextSort(a, "x");
    expect(d).toEqual({ id: "x", dir: "desc" });
    expect(nextSort(d, "x")).toBeNull();
    expect(nextSort(d, "y")).toEqual({ id: "y", dir: "asc" });
  });
});

describe("sanitizePrefs", () => {
  it("drops unknown columns, bad widths and page sizes, and never hides every column", () => {
    const p = sanitizePrefs({ hidden: ["a", "zzz", 3], widths: { a: 5, b: 99999, zzz: 100, c: "x" }, pageSize: 7 }, ["a", "b", "c"]);
    expect(p.hidden).toEqual(["a"]);
    expect(p.widths).toEqual({ a: MIN_COL, b: MAX_COL });
    expect(p.pageSize).toBeUndefined();
    expect(sanitizePrefs({ hidden: ["a", "b"] }, ["a", "b"]).hidden).toEqual([]);
    expect(sanitizePrefs({ pageSize: 50 }, ["a"]).pageSize).toBe(50);
  });
  it("copes with garbage", () => {
    expect(sanitizePrefs(null, ["a"])).toEqual({ hidden: [], widths: {} });
    expect(sanitizePrefs("x", ["a"])).toEqual({ hidden: [], widths: {} });
  });
});

describe("paging helpers", () => {
  it("clamps widths", () => { expect(clampWidth(1)).toBe(MIN_COL); expect(clampWidth(5000)).toBe(MAX_COL); expect(clampWidth(200.4)).toBe(200); });
  it("reports the visible range", () => {
    expect(pageRange(1, 25, 0)).toEqual({ from: 0, to: 0 });
    expect(pageRange(2, 25, 30)).toEqual({ from: 26, to: 30 });
    expect(pageRange(1, 25, 12)).toEqual({ from: 1, to: 12 });
  });
  it("builds a page window with gaps only where pages are skipped", () => {
    expect(pageWindow(1, 1)).toEqual([1]);
    expect(pageWindow(1, 5)).toEqual([1, 2, "gap", 5]);
    expect(pageWindow(10, 20)).toEqual([1, "gap", 9, 10, 11, "gap", 20]);
    expect(pageWindow(3, 20)).toEqual([1, 2, 3, 4, "gap", 20]);
  });
});
