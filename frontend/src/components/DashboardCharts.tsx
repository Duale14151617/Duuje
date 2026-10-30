import type { ReactNode } from "react";
import type { DayActivity, RegionHeadcount } from "../api/types";
import { useI18n } from "../i18n";
import { Icon, type IconName } from "./Icon";

/** Card that wraps one chart, styled like the other dashboard panels. */
export function ChartPanel({ icon, title, children }: { icon: IconName; title: string; children: ReactNode }) {
  return (
    <section className="panel chart-panel">
      <header><span className="ico"><Icon name={icon} size={18} /></span><h2>{title}</h2></header>
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
  return (
    <>
      <Legend items={[{ cls: "c1", label: t("dash.activePersonnel") }, { cls: "c2", label: t("dash.inactive") }]} />
      <ul className="hbars" aria-label={t("dash.byRegion")}>
        {rows.map((r) => {
          const label = r.code === null ? t("level.headquarters") : name(r);
          const inactive = r.total - r.active;
          return (
            <li key={r.code ?? "hq"} className="hb-row">
              <span className="hb-label">{label}</span>
              <span className="hb-track" aria-hidden="true">
                <span className="hb-seg c1" style={{ width: `${(r.active / max) * 100}%` }} />
                <span className="hb-seg c2" style={{ width: `${(inactive / max) * 100}%` }} />
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

const W = 320, H = 150, PAD = { top: 18, right: 8, bottom: 22, left: 8 };

/** Audit events per day for the last week: a column for all events (--chart-1) with the failed or denied part on top (--chart-2). */
export function ActivityChart({ days }: { days: DayActivity[] }) {
  const { t, lang } = useI18n();
  const max = Math.max(1, ...days.map((d) => d.events));
  const total = days.reduce((sum, d) => sum + d.events, 0);
  const slot = (W - PAD.left - PAD.right) / Math.max(1, days.length);
  const barW = Math.min(28, slot * 0.6);
  const plotH = H - PAD.top - PAD.bottom;
  const weekday = (iso: string) => {
    try { return new Intl.DateTimeFormat(lang, { weekday: "short" }).format(new Date(`${iso}T12:00:00`)); } catch { return iso.slice(5); }
  };
  if (total === 0) return <p className="muted chart-empty">{t("dash.noActivity")}</p>;
  return (
    <>
      <Legend items={[{ cls: "c1", label: t("dash.events") }, { cls: "c2", label: t("dash.activityIssues") }]} />
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("dash.activity7d")} preserveAspectRatio="xMidYMid meet">
        <line className="chart-axis" x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} />
        {days.map((d, i) => {
          const x = PAD.left + slot * i + (slot - barW) / 2;
          const h = (d.events / max) * plotH;
          const hi = (d.issues / max) * plotH;
          const y = H - PAD.bottom - h;
          return (
            <g key={d.date}>
              <title>{`${d.date}: ${d.events} / ${d.issues}`}</title>
              {d.events > 0 && <rect className="chart-col c1" x={x} y={y} width={barW} height={Math.max(h, 1)} rx={2} />}
              {d.issues > 0 && <rect className="chart-col c2" x={x} y={H - PAD.bottom - Math.max(hi, 2)} width={barW} height={Math.max(hi, 2)} rx={2} />}
              {d.events > 0 && <text className="chart-val" x={x + barW / 2} y={y - 4} textAnchor="middle">{d.events}</text>}
              <text className="chart-tick" x={x + barW / 2} y={H - 6} textAnchor="middle">{weekday(d.date)}</text>
            </g>
          );
        })}
      </svg>
      <table className="sr-only">
        <caption>{t("dash.activity7d")}</caption>
        <thead><tr><th scope="col">{t("dash.chartDate")}</th><th scope="col">{t("dash.events")}</th><th scope="col">{t("dash.activityIssues")}</th></tr></thead>
        <tbody>{days.map((d) => <tr key={d.date}><th scope="row">{d.date}</th><td>{d.events}</td><td>{d.issues}</td></tr>)}</tbody>
      </table>
    </>
  );
}
