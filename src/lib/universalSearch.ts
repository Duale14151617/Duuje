import { api, ApiError } from "../api/client";
import type { Asset, Named, Page, Person, SubmissionRow, StockLine, TrainingRec, Unit } from "../api/types";
import type { Key } from "../i18n";
import { matches, rankHits, type SearchHit, type SearchModule } from "./search";

/** Rows fetched per module. The "All" tab shows the first few of each; a module's own tab shows all of them. */
export const PER_MODULE = 8;
/** Lists with no server-side text search are read once (first page the user may see) and filtered here. */
const CLIENT_PAGE = 100;

export interface SearchDeps {
  t: (key: Key, vars?: Record<string, string | number>) => string;
  tr: (key: string) => string | undefined;
  name: (o: Named) => string;
  can: (permission: string) => boolean;
  /** Page-sized lists read once per open search, so typing more letters does not re-download them. */
  cache: Map<string, Promise<unknown>>;
}

interface VehicleRow {
  id: string; vehicle_id: string; plate: string; make: string; model: string; org_unit: Named & { id: string };
}

function once<T>(deps: SearchDeps, key: string, load: () => Promise<T>): Promise<T> {
  let p = deps.cache.get(key) as Promise<T> | undefined;
  if (!p) {
    p = load();
    deps.cache.set(key, p);
    p.catch(() => deps.cache.delete(key)); // a failed read is retried on the next keystroke
  }
  return p;
}

const status = (deps: SearchDeps, prefix: string, code: string) => deps.tr(`${prefix}.${code}`) ?? code;

async function personnel(term: string, d: SearchDeps): Promise<SearchHit[]> {
  const rows = d.can("search.cross_service")
    ? (await api<{ results: Person[] }>("/personnel/search/", { query: { q: term } })).results
    : (await api<Page<Person>>("/personnel/", { query: { q: term, page_size: PER_MODULE } })).results;
  return rows.slice(0, PER_MODULE).map((p) => ({
    module: "personnel", id: p.id, to: `/personnel/${p.id}`, title: p.full_name,
    subtitle: [`${p.rank.code} ${d.name(p.rank)}`.trim(), d.name(p.org_unit), p.service_number].filter(Boolean).join(" · "),
    badge: status(d, "pstatus", p.status),
  }));
}

async function units(term: string, d: SearchDeps): Promise<SearchHit[]> {
  const r = await api<Page<Unit>>("/organization/units/", { query: { q: term, page_size: PER_MODULE } });
  return r.results.map((u) => ({
    module: "units", id: u.id, to: `/units/${u.id}`, title: d.name(u),
    subtitle: [u.code, status(d, "level", u.level)].join(" · "), badge: u.active ? undefined : d.t("common.inactive"),
  }));
}

async function vehicles(term: string, d: SearchDeps): Promise<SearchHit[]> {
  const r = await api<Page<VehicleRow>>("/vehicles/", { query: { q: term, page_size: PER_MODULE } });
  return r.results.map((v) => ({
    module: "vehicles", id: v.id, to: `/vehicles/${v.id}`, title: v.vehicle_id,
    subtitle: [`${v.make} ${v.model}`.trim(), v.plate, d.name(v.org_unit)].filter(Boolean).join(" · "),
  }));
}

async function reports(term: string, d: SearchDeps): Promise<SearchHit[]> {
  const r = await once(d, "reports", () => api<Page<SubmissionRow>>("/reports/submissions/", { query: { page_size: CLIENT_PAGE } }));
  return r.results
    .filter((s) => matches([s.title, d.name(s.report_type), s.report_type.code, d.name(s.org_unit), s.org_unit.code, s.submitter_username, status(d, "rstatus", s.status)], term))
    .slice(0, PER_MODULE)
    .map((s) => ({
      module: "reports", id: s.id, to: `/reports/${s.id}`, title: s.title || d.name(s.report_type),
      subtitle: [d.name(s.report_type), d.name(s.org_unit), s.period_start].filter(Boolean).join(" · "), badge: status(d, "rstatus", s.status),
    }));
}

async function training(term: string, d: SearchDeps): Promise<SearchHit[]> {
  const r = await once(d, "training", () => api<Page<TrainingRec>>("/training/records/", { query: { page_size: CLIENT_PAGE } }));
  return r.results
    .filter((x) => matches([x.personnel.full_name, d.name(x.course), x.course.code, status(d, "tstatus", x.status)], term))
    .slice(0, PER_MODULE)
    .map((x) => ({
      module: "training", id: x.id, to: `/training/records/${x.id}`, title: x.personnel.full_name,
      subtitle: [d.name(x.course), d.name(x.personnel.org_unit)].join(" · "), badge: status(d, "tstatus", x.status),
    }));
}

async function logistics(term: string, d: SearchDeps): Promise<SearchHit[]> {
  const [assets, stock] = await Promise.allSettled([
    api<Page<Asset>>("/logistics/assets/", { query: { q: term, page_size: PER_MODULE } }),
    once(d, "stock", () => api<Page<StockLine>>("/logistics/stock/", { query: { page_size: CLIENT_PAGE } })),
  ]);
  if (assets.status === "rejected" && stock.status === "rejected") throw assets.reason;
  const out: SearchHit[] = [];
  if (assets.status === "fulfilled") {
    for (const a of assets.value.results) {
      out.push({ module: "logistics", id: `asset-${a.id}`, to: `/logistics/assets/${a.id}`, title: a.identifier,
        subtitle: [d.name(a.category), d.name(a.org_unit)].join(" · "), badge: status(d, "astatus", a.status) });
    }
  }
  if (stock.status === "fulfilled") {
    for (const s of stock.value.results.filter((x) => matches([d.name(x.category), x.category.code, d.name(x.org_unit)], term)).slice(0, PER_MODULE)) {
      out.push({ module: "logistics", id: `stock-${s.id}`, to: `/logistics/stock/${s.id}`, title: d.name(s.category),
        subtitle: [d.name(s.org_unit), `${s.quantity} ${s.uom}`].join(" · ") });
    }
  }
  return out.slice(0, PER_MODULE);
}

const RUN: Record<SearchModule, (term: string, d: SearchDeps) => Promise<SearchHit[]>> = { personnel, units, vehicles, reports, training, logistics };

export interface SearchOutcome {
  hits: SearchHit[];
  /** Modules that failed for a reason other than "you may not see this" (network, server error). */
  failed: SearchModule[];
  /** The session ended while searching. */
  signedOut: boolean;
}

/**
 * Ask every module the user can use, in parallel. Each module is an existing, already permission-checked list endpoint,
 * so the server alone decides what comes back: a 403/404 simply means that module contributes nothing.
 */
export async function runUniversalSearch(term: string, modules: SearchModule[], deps: SearchDeps): Promise<SearchOutcome> {
  const settled = await Promise.allSettled(modules.map((m) => RUN[m](term, deps)));
  const hits: SearchHit[] = [];
  const failed: SearchModule[] = [];
  let signedOut = false;
  settled.forEach((s, i) => {
    if (s.status === "fulfilled") { hits.push(...rankHits(s.value, term)); return; }
    const e = s.reason;
    if (e instanceof ApiError && e.code === "not_authenticated") signedOut = true;
    else if (e instanceof ApiError && (e.status === 403 || e.status === 404)) return;
    else failed.push(modules[i]);
  });
  return { hits, failed, signedOut };
}
