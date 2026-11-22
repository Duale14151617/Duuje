import type { ReactNode } from "react";
import type { DayActivity, RegionHeadcount } from "../api/types";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import { Icon, type IconName } from "./Icon";
import { useMedia } from "./useMedia";
import { EmptyState } from "./ui";

/** Card that wraps one chart, styled like the other dashboard panels. */
export function ChartPanel({ icon, title, actions, children }: { icon: IconName; title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel chart-panel">
      <header><span className="ico"><Icon name={icon} size={18} /></span><h2>{title}</h2>{actions && <div className="chart-actions">{actions}</div>}</header>
      {children}
    </section>
  );
}

function Legend({ items }: { items: { cls: string; label: string }[] }) {
  return (
    <ul className="chart-legend">
      {items.map((i) => <li key={i.cls}><span className={`swatch ${i.cls}`} aria-hidden="true" />{i.label}</li>)}
    </ul>
  );
}

type RegionSort = "total" | "inactive" | "name";

/**
 * Personnel per region: one bar per region, split into active (--chart-1) and not active (--chart-2).
 * Exact counts are written next to every bar (never only in a tooltip); hovering or focusing a row adds the share of all
 * personnel and the active rate. `linkFor` gives the personnel list a region may be opened in, or null when the signed-in
 * user may not open one (the label is then plain text). Sorting is local; it never changes what the server returned.
 */
export function RegionChart({ rows, linkFor }: { rows: RegionHeadcount[]; linkFor?: (row: RegionHeadcount) => { all: string; active: string } | null }) {
  const { t, name } = useI18n();
  const [sort, setSort] = useState<RegionSort>("total");
  if (rows.length === 0) return <EmptyState icon="map" title={t("dash.regionsEmptyTitle")} hint={t("dash.regionsEmptyHint")} />;
  const label = (r: RegionHeadcount) => (r.code === null ? t("level.headquarters") : name(r));
  const max = Math.max(1, ...rows.map((r) => r.total));
  const all = rows.reduce((n, r) => n + r.total, 0);
  const active = rows.reduce((n, r) => n + r.active, 0);
  const inactiveAll = all - active;
  const pct = (n: number, of: number) => (of > 0 ? Math.round((n / of) * 100) : 0);
  const sorted = [...rows].sort((a, b) => {
    const byName = label(a).localeCompare(label(b));
    if (sort === "name") return byName;
    const d = sort === "inactive" ? (b.total - b.active) - (a.total - a.active) : b.total - a.total;
    return d !== 0 ? d : byName;
  });
  const sorts: { id: RegionSort; text: string }[] = [
    { id: "total", text: t("dash.sortTotal") }, { id: "inactive", text: t("dash.sortInactive") }, { id: "name", text: t("dash.sortName") }];
  return (
    <>
      <div className="chart-stats">
        <span><b>{all.toLocaleString()}</b> {t("dash.personnelTitle")}</span>
        <span><b>{pct(active, all)}%</b> {t("dash.activePersonnel")}</span>
        <span className={inactiveAll > 0 ? "warnstat" : ""}><b>{inactiveAll.toLocaleString()}</b> {t("dash.inactive")}</span>
      </div>
      <div className="chart-toolbar">
        <Legend items={[
          { cls: "c1", label: `${t("dash.activePersonnel")} ${active.toLocaleString()}` },
          { cls: "c2", label: `${t("dash.inactive")} ${inactiveAll.toLocaleString()}` },
        ]} />
        <label className="chart-sort"><span>{t("dash.sortBy")}</span>
          <select value={sort} onChange={(e) => setSort(e.target.value as RegionSort)}>
            {sorts.map((o) => <option key={o.id} value={o.id}>{o.text}</option>)}
          </select>
        </label>
      </div>
      <ul className="hbars" aria-label={t("dash.byRegion")}>
        {sorted.map((r) => {
          const inactive = r.total - r.active;
          const links = linkFor?.(r) ?? null;
          const text = label(r);
          return (
            <li key={r.code ?? "hq"} className="hb-row">
              <span className="hb-label" title={text}>{links ? <Link to={links.all} aria-label={t("dash.viewRegion", { name: text })}>{text}</Link> : text}</span>
              <span className="hb-cell" tabIndex={0} aria-label={`${text}: ${t("dash.activePersonnel")} ${r.active.toLocaleString()}, ${t("dash.inactive")} ${inactive.toLocaleString()}, ${t("dash.regionTotal")} ${r.total.toLocaleString()}`}>
                <span className="hb-track" aria-hidden="true">
                  <span className="hb-seg c1" style={{ width: `${(r.active / max) * 100}%` }} />
                  <span className="hb-seg c2" style={{ width: `${(inactive / max) * 100}%`, minWidth: inactive > 0 ? 3 : undefined }} />
                </span>
                <span className="hb-tip" role="tooltip">
                  <b>{text}</b>
                  <span className="hb-tip-row"><span className="swatch c1" aria-hidden="true" />{t("dash.activePersonnel")}<b>{r.active.toLocaleString()}</b></span>
                  <span className="hb-tip-row"><span className="swatch c2" aria-hidden="true" />{t("dash.inactive")}<b>{inactive.toLocaleString()}</b></span>
                  <span className="hb-tip-row total">{t("dash.regionTotal")}<b>{r.total.toLocaleString()}</b></span>
                  <span className="muted">{t("dash.regionShare", { n: pct(r.total, all) })} · {t("dash.activeRate", { n: pct(r.active, r.total) })}</span>
                  {links && <Link className="hb-tip-link" to={links.active}>{t("dash.viewActive")}</Link>}
                </span>
              </span>
              <span className="hb-nums">
                <b>{r.total.toLocaleString()}</b>
                <span className="hb-split"><span className="c1t">{r.active.toLocaleString()}</span> / <span className={inactive > 0 ? "c2t" : "mutet"}>{inactive.toLocaleString()}</span></span>
              </span>
            </li>
          );
        })}
      </ul>
    </>
  );
}

/** Two-way switch for the activity chart's window (7 or 30 days). */
export function RangeSwitch({ value, onChange }: { value: 7 | 30; onChange: (days: 7 | 30) => void }) {
  const { t } = useI18n();
  return (
    <div className="range-switch" role="group" aria-label={t("dash.range")}>
      {([7, 30] as const).map((d) => (
        <button key={d} type="button" aria-pressed={value === d} onClick={() => onChange(d)}>
          {t(d === 7 ? "dash.range7" : "dash.range30")}
        </button>
      ))}
    </div>
  );
}

// Three drawings, so the text stays readable at every card width: a phone card (about 330px), a desktop panel
// (about 480 to 650px) and a wide-screen panel (700px and more). The svg then scales only slightly with the card.
const SIZES = {
  wide: { W: 520, H: 220, PAD: { top: 24, right: 8, bottom: 30, left: 34 } },
  xl: { W: 720, H: 250, PAD: { top: 26, right: 10, bottom: 32, left: 38 } },
  narrow: { W: 340, H: 210, PAD: { top: 22, right: 6, bottom: 48, left: 30 } },
};

/** Round a maximum up to an easy-to-read axis top (139 becomes 150, 6 stays 6). */
function niceCeil(n: number): number {
  if (n <= 4) return Math.max(1, n);
  const pow = 10 ** Math.floor(Math.log10(n));
  const step = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((m) => m * pow).find((v) => v >= n);
  return Math.ceil(step ?? n);
}

/**
 * Audit events per day. Each day has two columns side by side: all events (--chart-1) and the failed or denied
 * ones (--chart-issue, red), so issues stay visible even when they are a tiny share of the day. The legend entries are
 * switches that hide a series (the scale follows), and hovering or focusing a day (Tab, then arrow keys work through the
 * normal tab order) writes its exact figures above the chart. With a week the columns carry their counts; with a month
 * only every fifth day is labelled and the exact figures are in the readout and the screen-reader table.
 */
export function ActivityChart({ days }: { days: DayActivity[] }) {
  const { t, lang } = useI18n();
  const narrow = useMedia("(max-width: 599px)");
  const huge = useMedia("(min-width: 1700px)");
  const { W, H, PAD } = narrow ? SIZES.narrow : huge ? SIZES.xl : SIZES.wide;
  const [show, setShow] = useState({ events: true, issues: true });
  const [pick, setPick] = useState<number | null>(null);
  const dense = days.length > 14;
  const total = days.reduce((sum, d) => sum + d.events, 0);
  const issuesTotal = days.reduce((sum, d) => sum + d.issues, 0);
  const title = t(dense ? "dash.activity30d" : "dash.activity7d");
  const peak = days.reduce((best, d) => (d.events > best.events ? d : best), days[0] ?? { date: "", events: 0, issues: 0 });
  const top = niceCeil(Math.max(1, ...days.map((d) => Math.max(show.events ? d.events : 0, show.issues ? d.issues : 0))));
  const slot = (W - PAD.left - PAD.right) / Math.max(1, days.length);
  const bigger = huge ? 1.35 : 1;
  const evW = dense ? Math.min((narrow ? 5 : 8) * bigger, slot * 0.5) : Math.min((narrow ? 16 : 26) * bigger, slot * 0.4);
  const isW = dense ? Math.min((narrow ? 3 : 5) * bigger, slot * 0.3) : Math.min((narrow ? 9 : 14) * bigger, slot * 0.22);
  const gap = dense ? 1 : 2;
  const groupW = evW + gap + isW;
  const plotH = H - PAD.top - PAD.bottom;
  const base = H - PAD.bottom;
  const grid = [0, top / 2, top].map((v) => ({ v, y: base - (v / top) * plotH }));
  const fmt = (iso: string, opts: Intl.DateTimeFormatOptions) => {
    try { return new Intl.DateTimeFormat(lang, opts).format(new Date(`${iso}T12:00:00`)); } catch { return iso.slice(5); }
  };
  if (total === 0) return <p className="muted chart-empty">{t(dense ? "dash.noActivity30d" : "dash.noActivity")}</p>;
  const shown = pick !== null ? days[pick] : null;
  const toggle = (k: "events" | "issues") => setShow((s) => (s[k] && !s[other(k)] ? s : { ...s, [k]: !s[k] }));  // keep one series visible
  const other = (k: "events" | "issues") => (k === "events" ? "issues" : "events");
  const items = [
    { k: "events" as const, cls: "c1", label: t("dash.events") },
    { k: "issues" as const, cls: "issue", label: t("dash.activityIssues") },
  ];
  return (
    <>
      <div className="chart-stats">
        <span><b>{total.toLocaleString()}</b> {t("dash.events")}</span>
        <span className={issuesTotal > 0 ? "issue" : ""}><b>{issuesTotal.toLocaleString()}</b> {t("dash.activityIssues")}</span>
        <span className={issuesTotal > 0 ? "issue" : ""}>{t("dash.issueRate", { n: total > 0 ? Math.round((issuesTotal / total) * 1000) / 10 : 0 })}</span>
      </div>
      <ul className="chart-legend chart-switches">
        {items.map((i) => (
          <li key={i.k}>
            <button type="button" className="legend-btn" aria-pressed={show[i.k]} title={t(show[i.k] ? "dash.hideSeries" : "dash.showSeries", { name: i.label })} onClick={() => toggle(i.k)}>
              <span className={`swatch ${i.cls}`} aria-hidden="true" />{i.label}
            </button>
          </li>
        ))}
      </ul>
      <p className="chart-readout" aria-live="polite">
        {shown
          ? t("dash.dayDetail", { date: fmt(shown.date, { weekday: "long", day: "numeric", month: "long" }), events: shown.events.toLocaleString(), issues: shown.issues.toLocaleString() })
          : <span className="muted">{t("dash.busiestDay")}: {fmt(peak.date, { weekday: "short", day: "numeric", month: "short" })} · {peak.events.toLocaleString()}</span>}
      </p>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="group" aria-label={title} preserveAspectRatio="xMidYMid meet" onMouseLeave={() => setPick(null)}>
        {grid.map((g) => (
          <g key={g.v}>
            <line className={g.v === 0 ? "chart-axis" : "chart-grid"} x1={PAD.left} x2={W - PAD.right} y1={g.y} y2={g.y} />
            <text className="chart-yt" x={PAD.left - 6} y={g.y + 4} textAnchor="end">{Math.round(g.v)}</text>
          </g>
        ))}
        {days.map((d, i) => {
          const gx = PAD.left + slot * i + (slot - groupW) / 2;
          const cx = PAD.left + slot * i + slot / 2;
          const he = Math.max((d.events / top) * plotH, 2);
          const hi = Math.max((d.issues / top) * plotH, 4);
          const isToday = i === days.length - 1;
          const labelled = dense ? (i % 5 === 0 && days.length - 1 - i >= 4) || isToday : true;
          const tickDate = dense ? fmt(d.date, { day: "numeric", month: "short" }) : fmt(d.date, { day: "numeric" });
          return (
            <g key={d.date} className={pick === i ? "chart-day on" : "chart-day"} tabIndex={0} role="img"
               aria-label={t("dash.dayDetail", { date: d.date, events: d.events, issues: d.issues })}
               onMouseEnter={() => setPick(i)} onFocus={() => setPick(i)} onBlur={() => setPick(null)}>
              <rect className="chart-hit" x={PAD.left + slot * i} y={PAD.top - 6} width={slot} height={plotH + 6} />
              {show.events && d.events > 0 && <rect className="chart-col c1" x={gx} y={base - he} width={evW} height={he} rx={2} />}
              {show.issues && d.issues > 0 && <rect className="chart-col c2" x={gx + evW + gap} y={base - hi} width={isW} height={hi} rx={2} />}
              {!dense && show.events && d.events > 0 && <text className="chart-val" x={gx + evW / 2} y={base - he - 6} textAnchor="middle">{d.events}</text>}
              {/* wide: the issue count sits above its red column; narrow: in its own row under the date so it never touches the event count */}
              {!dense && show.issues && d.issues > 0 && !narrow && <text className="chart-issue-val" x={gx + evW + gap + isW / 2} y={base - hi - 6} textAnchor="middle">{d.issues}</text>}
              {!dense && show.issues && d.issues > 0 && narrow && <text className="chart-issue-val" x={cx} y={base + 38} textAnchor="middle">{d.issues}</text>}
              {labelled && (
                <text className={isToday ? "chart-tick today" : "chart-tick"} x={cx} y={base + 19} textAnchor="middle">
                  {!dense && <tspan>{fmt(d.date, { weekday: "short" })}</tspan>}
                  <tspan className="chart-date" dx={dense ? 0 : 4}>{tickDate}</tspan>
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <table className="sr-only">
        <caption>{title}</caption>
        <thead><tr><th scope="col">{t("dash.chartDate")}</th><th scope="col">{t("dash.events")}</th><th scope="col">{t("dash.activityIssues")}</th></tr></thead>
        <tbody>{days.map((d) => <tr key={d.date}><th scope="row">{d.date}</th><td>{d.events}</td><td>{d.issues}</td></tr>)}</tbody>
      </table>
    </>
  );
}
