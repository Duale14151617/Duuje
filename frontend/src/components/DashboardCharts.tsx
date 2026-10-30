import type { ReactNode } from "react";
import type { DayActivity, RegionHeadcount } from "../api/types";
import { useI18n } from "../i18n";
import { Icon, type IconName } from "./Icon";
import { useMedia } from "./useMedia";

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

/** Personnel per region: one bar per region, split into active (--chart-1) and not active (--chart-2). */
export function RegionChart({ rows }: { rows: RegionHeadcount[] }) {
  const { t, name } = useI18n();
  const max = Math.max(1, ...rows.map((r) => r.total));
  const active = rows.reduce((sum, r) => sum + r.active, 0);
  const inactiveAll = rows.reduce((sum, r) => sum + (r.total - r.active), 0);
  return (
    <>
      <Legend items={[
        { cls: "c1", label: `${t("dash.activePersonnel")} ${active.toLocaleString()}` },
        { cls: "c2", label: `${t("dash.inactive")} ${inactiveAll.toLocaleString()}` },
      ]} />
      <ul className="hbars" aria-label={t("dash.byRegion")}>
        {rows.map((r) => {
          const label = r.code === null ? t("level.headquarters") : name(r);
          const inactive = r.total - r.active;
          return (
            <li key={r.code ?? "hq"} className="hb-row">
              <span className="hb-label">{label}</span>
              <span className="hb-track" aria-hidden="true">
                <span className="hb-seg c1" style={{ width: `${(r.active / max) * 100}%` }} />
                <span className="hb-seg c2" style={{ width: `${(inactive / max) * 100}%`, minWidth: inactive > 0 ? 3 : undefined }} />
              </span>
              <b className="hb-value">{r.total.toLocaleString()}</b>
              <span className="sr-only">{t("dash.activePersonnel")}: {r.active.toLocaleString()}, {t("dash.inactive")}: {inactive.toLocaleString()}</span>
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

// Two drawings, so the text stays readable at either card width: a desktop panel (about 480 to 650px wide)
// and a phone card (about 330px). The svg then scales only slightly with the card.
const SIZES = {
  wide: { W: 520, H: 220, PAD: { top: 24, right: 8, bottom: 30, left: 34 } },
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
 * ones (--chart-issue, red), so issues stay visible even when they are a tiny share of the day. With a week the
 * columns carry their counts and every weekday is labelled; with a month (dense) only every fifth day is labelled
 * and the exact figures are in each column's tooltip and the screen-reader table. The last day (today) is bold.
 */
export function ActivityChart({ days }: { days: DayActivity[] }) {
  const { t, lang } = useI18n();
  const narrow = useMedia("(max-width: 599px)");
  const { W, H, PAD } = narrow ? SIZES.narrow : SIZES.wide;
  const dense = days.length > 14;
  const total = days.reduce((sum, d) => sum + d.events, 0);
  const issuesTotal = days.reduce((sum, d) => sum + d.issues, 0);
  const title = t(dense ? "dash.activity30d" : "dash.activity7d");
  const top = niceCeil(Math.max(1, ...days.map((d) => d.events)));
  const slot = (W - PAD.left - PAD.right) / Math.max(1, days.length);
  const evW = dense ? Math.min(narrow ? 5 : 8, slot * 0.5) : Math.min(narrow ? 16 : 26, slot * 0.4);
  const isW = dense ? Math.min(narrow ? 3 : 5, slot * 0.3) : Math.min(narrow ? 9 : 14, slot * 0.22);
  const gap = dense ? 1 : 2;
  const groupW = evW + gap + isW;
  const plotH = H - PAD.top - PAD.bottom;
  const base = H - PAD.bottom;
  const grid = [0, top / 2, top].map((v) => ({ v, y: base - (v / top) * plotH }));
  const fmt = (iso: string, opts: Intl.DateTimeFormatOptions) => {
    try { return new Intl.DateTimeFormat(lang, opts).format(new Date(`${iso}T12:00:00`)); } catch { return iso.slice(5); }
  };
  if (total === 0) return <p className="muted chart-empty">{t(dense ? "dash.noActivity30d" : "dash.noActivity")}</p>;
  return (
    <>
      <div className="chart-stats">
        <span><b>{total.toLocaleString()}</b> {t("dash.events")}</span>
        <span className={issuesTotal > 0 ? "issue" : ""}><b>{issuesTotal.toLocaleString()}</b> {t("dash.activityIssues")}</span>
      </div>
      <Legend items={[{ cls: "c1", label: t("dash.events") }, { cls: "issue", label: t("dash.activityIssues") }]} />
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} preserveAspectRatio="xMidYMid meet">
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
            <g key={d.date}>
              <title>{`${d.date}: ${d.events} / ${d.issues}`}</title>
              {d.events > 0 && <rect className="chart-col c1" x={gx} y={base - he} width={evW} height={he} rx={2} />}
              {d.issues > 0 && <rect className="chart-col c2" x={gx + evW + gap} y={base - hi} width={isW} height={hi} rx={2} />}
              {!dense && d.events > 0 && <text className="chart-val" x={gx + evW / 2} y={base - he - 6} textAnchor="middle">{d.events}</text>}
              {/* wide: the issue count sits above its red column; narrow: in its own row under the date so it never touches the event count */}
              {!dense && d.issues > 0 && !narrow && <text className="chart-issue-val" x={gx + evW + gap + isW / 2} y={base - hi - 6} textAnchor="middle">{d.issues}</text>}
              {!dense && d.issues > 0 && narrow && <text className="chart-issue-val" x={cx} y={base + 38} textAnchor="middle">{d.issues}</text>}
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
