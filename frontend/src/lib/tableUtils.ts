/** Pure helpers behind the shared DataTable: sorting, saved column preferences and page maths. No React here, so they are unit-tested directly. */

export type SortDir = "asc" | "desc";
export interface SortState { id: string; dir: SortDir }
export type SortValue = string | number | null | undefined;

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** Empty values always sort last, whichever direction is chosen (handled in sortRows). Numbers compare numerically, text with natural ordering ("2" < "10"). */
export function compareValues(a: SortValue, b: SortValue): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return collator.compare(String(a), String(b));
}

const isEmpty = (v: SortValue) => v === null || v === undefined || v === "";

/** Stable sort of a copy; `get` is null when the column has no sort key, in which case the order is left alone. */
export function sortRows<R>(rows: readonly R[], get: ((row: R) => SortValue) | null | undefined, dir: SortDir): R[] {
  if (!get) return [...rows];
  return rows
    .map((row, index) => ({ row, index, value: get(row) }))
    .sort((x, y) => {
      const xe = isEmpty(x.value), ye = isEmpty(y.value);
      if (xe || ye) return xe && ye ? x.index - y.index : xe ? 1 : -1;
      const c = compareValues(x.value, y.value);
      return c !== 0 ? (dir === "asc" ? c : -c) : x.index - y.index;
    })
    .map((x) => x.row);
}

/** Header click cycles: ascending, descending, then back to the original order. */
export function nextSort(current: SortState | null, id: string): SortState | null {
  if (!current || current.id !== id) return { id, dir: "asc" };
  return current.dir === "asc" ? { id, dir: "desc" } : null;
}

export interface TablePrefs { hidden: string[]; widths: Record<string, number>; pageSize?: number }
export const MIN_COL = 64;
export const MAX_COL = 640;
export const PAGE_SIZES = [10, 25, 50, 100] as const;

export const clampWidth = (w: number, min = MIN_COL, max = MAX_COL) => Math.min(max, Math.max(min, Math.round(w)));

/** Saved preferences come from localStorage, so treat them as untrusted: drop unknown columns, bad numbers, and never hide every column. */
export function sanitizePrefs(raw: unknown, validIds: readonly string[]): TablePrefs {
  const out: TablePrefs = { hidden: [], widths: {} };
  if (!raw || typeof raw !== "object") return out;
  const r = raw as Record<string, unknown>;
  const valid = new Set(validIds);
  if (Array.isArray(r.hidden)) out.hidden = r.hidden.filter((x): x is string => typeof x === "string" && valid.has(x));
  if (out.hidden.length >= validIds.length) out.hidden = [];
  if (r.widths && typeof r.widths === "object") {
    for (const [k, v] of Object.entries(r.widths as Record<string, unknown>)) {
      if (valid.has(k) && typeof v === "number" && Number.isFinite(v)) out.widths[k] = clampWidth(v);
    }
  }
  if (typeof r.pageSize === "number" && (PAGE_SIZES as readonly number[]).includes(r.pageSize)) out.pageSize = r.pageSize;
  return out;
}

/** 1-based inclusive range shown as "from to of count"; zeros when there is nothing. */
export function pageRange(page: number, pageSize: number, count: number): { from: number; to: number } {
  if (count <= 0) return { from: 0, to: 0 };
  const from = (Math.max(1, page) - 1) * pageSize + 1;
  return { from: Math.min(from, count), to: Math.min(count, from + pageSize - 1) };
}

/** Page buttons with gaps: 1 … 4 5 [6] 7 8 … 20. */
export function pageWindow(page: number, total: number, around = 1): (number | "gap")[] {
  if (total <= 1) return [1];
  const keep = new Set<number>([1, total]);
  for (let p = page - around; p <= page + around; p++) if (p >= 1 && p <= total) keep.add(p);
  const sorted = [...keep].sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push(p - sorted[i - 1] === 2 ? sorted[i - 1] + 1 : "gap");
    out.push(p);
  });
  return out;
}
