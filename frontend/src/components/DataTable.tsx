import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { useI18n } from "../i18n";
import {
  MAX_COL, MIN_COL, PAGE_SIZES, clampWidth, nextSort, sanitizePrefs, sortRows,
  type SortState, type SortValue, type TablePrefs,
} from "../lib/tableUtils";
import { Icon } from "./Icon";
import { EmptyState, Pager } from "./ui";

export interface Column<R> {
  /** Stable id: saved column choices are stored against it. */
  id: string;
  /** Already translated. */
  header: string;
  cell: (row: R) => ReactNode;
  /** Makes the column sortable. Return null for "no value" (those rows always sort last). */
  sort?: (row: R) => SortValue;
  align?: "left" | "right";
  /** Starting width in pixels (the user can drag it). */
  width?: number;
  /** Hidden until the user turns it on from the Columns menu. */
  hidden?: boolean;
  /** Cannot be hidden (the column that identifies the row). */
  locked?: boolean;
}

interface Props<R> {
  /** Names the table for saved preferences, e.g. "personnel". */
  id: string;
  /** Accessible name of the table. */
  caption: string;
  columns: Column<R>[];
  rows: R[] | null | undefined;
  rowKey: (row: R) => string;
  loading?: boolean;
  /** Shown when there are no rows and no filter is active. */
  empty: { icon?: Parameters<typeof EmptyState>[0]["icon"]; title: string; hint?: string; action?: ReactNode };
  /** True when search or filters are narrowing the list; an empty result then says "no match" and offers a reset. */
  filtered?: boolean;
  onReset?: () => void;
  /** Extra buttons on the right of the table toolbar (exports and the like). */
  actions?: ReactNode;
  /** Server-side paging: the page owns `page`, fetches it, and passes the total. */
  page?: number;
  count?: number;
  pageSize?: number;
  onPage?: (page: number) => void;
  /** Offer a rows-per-page choice (server paging); the page must pass the value to its request. */
  onPageSize?: (size: number) => void;
  /** Client-side paging for lists the page already holds in full. */
  clientPageSize?: number;
  initialSort?: SortState | null;
  rowClass?: (row: R) => string | undefined;
}

const DEFAULT_WIDTH = 160;
const storeKey = (id: string) => `armyhq.table.${id}`;

function loadPrefs(id: string, validIds: string[]): TablePrefs | null {
  try {
    const raw = localStorage.getItem(storeKey(id));
    return raw === null ? null : sanitizePrefs(JSON.parse(raw), validIds);
  } catch { return null; }
}
function savePrefs(id: string, prefs: TablePrefs | null) {
  try {
    if (prefs === null) localStorage.removeItem(storeKey(id));
    else localStorage.setItem(storeKey(id), JSON.stringify(prefs));
  } catch { /* preference only */ }
}

/**
 * The one table used by every list in the app: sticky header, click-to-sort headers, show/hide and drag-to-resize columns
 * (remembered per browser), numbered paging, loading skeleton and empty states. On phones the rows become stacked cards.
 * Sorting applies to the rows loaded now; with server paging that is the current page, and the footer says so.
 */
export function DataTable<R>({
  id, caption, columns, rows, rowKey, loading = false, empty, filtered = false, onReset, actions,
  page = 1, count, pageSize, onPage, onPageSize, clientPageSize, initialSort = null, rowClass,
}: Props<R>) {
  const { t } = useI18n();
  const uid = useId();
  const ids = useMemo(() => columns.map((c) => c.id), [columns]);
  const defaultHidden = useMemo(() => columns.filter((c) => c.hidden).map((c) => c.id), [columns]);

  const [prefs, setPrefs] = useState<TablePrefs>(() => loadPrefs(id, ids) ?? { hidden: defaultHidden, widths: {} });
  const [sort, setSort] = useState<SortState | null>(initialSort);
  const [localPage, setLocalPage] = useState(1);
  const [clientSize, setClientSize] = useState<number>(clientPageSize ?? 25);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const [live, setLive] = useState("");

  const commit = useCallback((next: TablePrefs) => { setPrefs(next); savePrefs(id, next); }, [id]);

  // close the Columns menu on outside click or Escape
  useEffect(() => {
    if (!menu) return;
    const down = (e: globalThis.PointerEvent) => { if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false); };
    const key = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") setMenu(false); };
    document.addEventListener("pointerdown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("pointerdown", down); document.removeEventListener("keydown", key); };
  }, [menu]);

  const visible = columns.filter((c) => c.locked || !prefs.hidden.includes(c.id));
  const sortCol = sort ? columns.find((c) => c.id === sort.id) : undefined;
  const sorted = useMemo(
    () => (rows ? sortRows(rows, sortCol?.sort ?? null, sort?.dir ?? "asc") : null),
    [rows, sortCol, sort?.dir],
  );

  const serverPaged = !!onPage;
  const size = serverPaged ? (pageSize ?? 25) : clientSize;
  const total = serverPaged ? (count ?? rows?.length ?? 0) : (sorted?.length ?? 0);
  const lastPage = Math.max(1, Math.ceil(total / size));
  const curPage = serverPaged ? page : Math.min(localPage, lastPage);
  const shown = serverPaged || !sorted ? sorted : sorted.slice((curPage - 1) * size, curPage * size);
  const goPage = (p: number) => (serverPaged ? onPage!(p) : setLocalPage(p));
  const changeSize = (n: number) => { if (serverPaged) onPageSize?.(n); else { setClientSize(n); setLocalPage(1); } };

  const toggleSort = (col: Column<R>) => {
    if (!col.sort) return;
    const next = nextSort(sort, col.id);
    setSort(next);
    setLive(next ? t(next.dir === "asc" ? "table.sortedAsc" : "table.sortedDesc", { name: col.header }) : t("table.sortCleared"));
    if (!serverPaged) setLocalPage(1);
  };

  // ---- column resizing: drag the handle, or focus it and use the arrow keys ----
  const drag = useRef<{ id: string; x: number; w: number } | null>(null);
  const liveWidths = useRef(prefs.widths);
  liveWidths.current = prefs.widths;
  const startDrag = (col: Column<R>) => (e: PointerEvent<HTMLElement>) => {
    const th = e.currentTarget.closest("th");
    if (!th) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { id: col.id, x: e.clientX, w: th.getBoundingClientRect().width };
  };
  const moveDrag = (e: PointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d) return;
    setPrefs((p) => ({ ...p, widths: { ...p.widths, [d.id]: clampWidth(d.w + e.clientX - d.x) } }));
  };
  const endDrag = (e: PointerEvent<HTMLElement>) => {
    if (!drag.current) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    savePrefs(id, { ...prefs, widths: liveWidths.current });
  };
  const keyResize = (col: Column<R>) => (e: KeyboardEvent<HTMLElement>) => {
    const step = e.shiftKey ? 48 : 16;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const th = e.currentTarget.closest("th");
    const base = prefs.widths[col.id] ?? th?.getBoundingClientRect().width ?? col.width ?? DEFAULT_WIDTH;
    commit({ ...prefs, widths: { ...prefs.widths, [col.id]: clampWidth(base + (e.key === "ArrowRight" ? step : -step)) } });
  };

  const widthOf = (c: Column<R>) => prefs.widths[c.id] ?? c.width ?? DEFAULT_WIDTH;
  const tableMin = visible.reduce((n, c) => n + widthOf(c), 0);
  const customised = prefs.hidden.join() !== defaultHidden.join() || Object.keys(prefs.widths).length > 0;
  const sortable = columns.filter((c) => c.sort && (c.locked || !prefs.hidden.includes(c.id)));
  const first = loading && !rows;
  const none = !first && sorted !== null && sorted.length === 0;

  return (
    <section className="dt" aria-busy={loading}>
      <div className="dt-toolbar">
        <span className="dt-count muted" aria-live="polite">{first ? t("common.loading") : t("table.results", { count: total })}</span>
        <div className="dt-tools">
          {sortable.length > 0 && (
            <div className="dt-mobile-sort">
              <label className="sr-only" htmlFor={`${uid}-sort`}>{t("table.sortBy")}</label>
              <select id={`${uid}-sort`} value={sort?.id ?? ""} onChange={(e) => setSort(e.target.value ? { id: e.target.value, dir: sort?.dir ?? "asc" } : null)}>
                <option value="">{t("table.sortBy")}</option>
                {sortable.map((c) => <option key={c.id} value={c.id}>{c.header}</option>)}
              </select>
              {sort && <button type="button" className="secondary sm icon-btn" aria-label={t(sort.dir === "asc" ? "table.sortedAsc" : "table.sortedDesc", { name: sortCol?.header ?? "" })}
                               onClick={() => setSort({ ...sort, dir: sort.dir === "asc" ? "desc" : "asc" })}><Icon name={sort.dir === "asc" ? "chevronUp" : "chevronDown"} size={16} /></button>}
            </div>
          )}
          <div className="dt-menu" ref={menuRef}>
            <button type="button" className="secondary sm" aria-haspopup="true" aria-expanded={menu} aria-controls={`${uid}-cols`} onClick={() => setMenu((v) => !v)}>
              <Icon name="columns" size={16} /> <span>{t("table.columns")}</span>
            </button>
            {menu && (
              <div className="dt-pop" id={`${uid}-cols`} role="group" aria-label={t("table.columns")}>
                {columns.map((c) => (
                  <label key={c.id} className="dt-check">
                    <input type="checkbox" checked={c.locked || !prefs.hidden.includes(c.id)} disabled={c.locked}
                           onChange={(e) => {
                             const hidden = e.target.checked ? prefs.hidden.filter((x) => x !== c.id) : [...prefs.hidden, c.id];
                             if (hidden.length < columns.length) commit({ ...prefs, hidden });
                           }} />
                    <span>{c.header}</span>
                  </label>
                ))}
                <button type="button" className="ghost sm" disabled={!customised}
                        onClick={() => { setPrefs({ hidden: defaultHidden, widths: {} }); savePrefs(id, null); }}>{t("table.columnsReset")}</button>
              </div>
            )}
          </div>
          {actions}
        </div>
      </div>
      <p className="sr-only" role="status" aria-live="polite">{live}</p>

      {none ? (
        filtered
          ? <EmptyState icon="search" title={t("table.noMatch")} hint={t("table.noMatchHint")}
                        action={onReset ? <button type="button" className="secondary" onClick={onReset}>{t("filter.reset")}</button> : undefined} />
          : <EmptyState icon={empty.icon} title={empty.title} hint={empty.hint} action={empty.action} />
      ) : (
        <div className={`dt-scroll${loading && rows ? " is-loading" : ""}`} tabIndex={0} role="region" aria-label={caption}>
          <table style={{ minWidth: tableMin }}>
            <caption className="sr-only">{caption}</caption>
            <colgroup>{visible.map((c) => <col key={c.id} style={{ width: widthOf(c) }} />)}</colgroup>
            <thead>
              <tr>
                {visible.map((c) => {
                  const active = sort?.id === c.id;
                  return (
                    <th key={c.id} scope="col" className={c.align === "right" ? "num" : undefined}
                        aria-sort={c.sort ? (active ? (sort!.dir === "asc" ? "ascending" : "descending") : "none") : undefined}>
                      {c.sort ? (
                        <button type="button" className={`dt-sort${active ? " on" : ""}`} onClick={() => toggleSort(c)}>
                          <span>{c.header}</span>
                          <Icon name={active ? (sort!.dir === "asc" ? "chevronUp" : "chevronDown") : "sort"} size={14} />
                        </button>
                      ) : <span className="dt-head">{c.header}</span>}
                      <span className="dt-resize" role="separator" aria-orientation="vertical" tabIndex={0}
                            aria-label={t("table.resize", { name: c.header })} aria-valuemin={MIN_COL} aria-valuemax={MAX_COL}
                            aria-valuenow={Math.round(widthOf(c))}
                            onPointerDown={startDrag(c)} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onKeyDown={keyResize(c)} />
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {first
                ? Array.from({ length: 6 }, (_, r) => (
                    <tr key={`s${r}`} className="dt-skel" aria-hidden="true">{visible.map((c) => <td key={c.id} data-label={c.header}><span className="skeleton-line" /></td>)}</tr>
                  ))
                : shown?.map((row) => (
                    <tr key={rowKey(row)} className={rowClass?.(row)}>
                      {visible.map((c) => <td key={c.id} data-label={c.header} className={c.align === "right" ? "num" : undefined}>{c.cell(row)}</td>)}
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      )}

      {!first && !none && (
        <div className="dt-foot">
          <div className="dt-foot-left">
            {(serverPaged ? !!onPageSize : total > PAGE_SIZES[0]) && (
              <label className="dt-size">
                <span className="muted">{t("table.rowsPerPage")}</span>
                <select value={size} onChange={(e) => changeSize(Number(e.target.value))}>
                  {(PAGE_SIZES as readonly number[]).includes(size) ? null : <option value={size}>{size}</option>}
                  {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            )}
            {serverPaged && sort && total > (rows?.length ?? 0) && <span className="muted small-note">{t("table.sortedPage")}</span>}
          </div>
          <Pager page={curPage} count={total} pageSize={size} onPage={goPage} />
        </div>
      )}
    </section>
  );
}
