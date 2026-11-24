/** Pure logic for the universal search: which modules a user can query, matching, and ranking. No network or React here. */

export type SearchModule = "personnel" | "units" | "vehicles" | "reports" | "training" | "logistics";
export const SEARCH_MODULES: SearchModule[] = ["personnel", "units", "vehicles", "reports", "training", "logistics"];
export const MIN_QUERY = 2;

export interface SearchHit {
  module: SearchModule;
  id: string;
  /** In-app route; the destination page enforces its own permissions again. */
  to: string;
  title: string;
  subtitle: string;
  /** Short status text shown at the end of the row (already translated). */
  badge?: string;
}

/** Lower-case, strip accents and collapse whitespace so "Cabdi  Xasan" and "cabdi xasan" match. */
export function normalize(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
}

/** Every word typed must appear somewhere in the searchable text (order does not matter). */
export function matches(fields: readonly (string | null | undefined)[], term: string): boolean {
  const words = normalize(term).split(" ").filter(Boolean);
  if (words.length === 0) return false;
  const hay = normalize(fields.filter(Boolean).join(" "));
  return words.every((w) => hay.includes(w));
}

/** 0 = best. Exact title, then title prefix, then a word in the title starting with the term, then anything else. */
export function rankHit(hit: Pick<SearchHit, "title">, term: string): number {
  const t = normalize(hit.title), q = normalize(term);
  if (t === q) return 0;
  if (t.startsWith(q)) return 1;
  if (t.split(" ").some((w) => w.startsWith(q))) return 2;
  return t.includes(q) ? 3 : 4;
}

/** Stable: hits of equal rank keep the order the server returned them in. */
export function rankHits<T extends Pick<SearchHit, "title">>(hits: readonly T[], term: string): T[] {
  return hits.map((h, i) => ({ h, i, r: rankHit(h, term) })).sort((a, b) => a.r - b.r || a.i - b.i).map((x) => x.h);
}

/** Which modules to query for this user. Mirrors the sidebar rules; the server still decides what each query may return. */
export function searchableModules(can: (permission: string) => boolean): SearchModule[] {
  const out: SearchModule[] = [];
  if (can("search.cross_service") || can("personnel.view") || can("personnel.view_team")) out.push("personnel");
  if (can("org.view")) out.push("units");
  if (can("vehicles.view")) out.push("vehicles");
  if (can("reports.view")) out.push("reports");
  if (["training.view", "training.configure", "training.report"].some(can)) out.push("training");
  if (["logistics.view", "logistics.restricted", "logistics.configure", "logistics.approve", "logistics.restricted_approve", "logistics.report"].some(can)) out.push("logistics");
  return out;
}
