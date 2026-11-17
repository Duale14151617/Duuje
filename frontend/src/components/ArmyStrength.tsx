import { useState } from "react";
import type { CombinedReport } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ErrorNotice, Loading, Notice, formatDate } from "./ui";
import { useI18n, type Key } from "../i18n";

/** Line of serving personnel per recorded day. Decorative shape plus a text summary, so it reads without the picture. */
function TrendLine({ points }: { points: { date: string; serving: number }[] }) {
  const { t, lang } = useI18n();
  const W = 320, H = 70, P = 6;
  const ys = points.map((p) => p.serving);
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const x = (i: number) => P + (i * (W - 2 * P)) / (points.length - 1);
  const y = (v: number) => H - P - ((v - lo) * (H - 2 * P)) / span;
  const first = points[0], last = points[points.length - 1];
  const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(lang === "so" ? "so-SO" : "en-GB", { dateStyle: "medium" });
  return (
    <>
      <h3>{t("comb.trend")}</h3>
      <svg className="trend-line" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("comb.trend")}>
        <polyline points={points.map((p, i) => `${x(i)},${y(p.serving)}`).join(" ")} fill="none" />
        <circle cx={x(points.length - 1)} cy={y(last.serving)} r="3" />
      </svg>
      <p className="muted small">{t("comb.trendChange", { from: day(first.date), to: day(last.date), a: first.serving, b: last.serving })}</p>
    </>
  );
}

/** Army strength for the reports page. Aggregates only. The figures are loaded only when the card is opened, because the server audits every view. */
export function ArmyStrength() {
  const { t, lang, name, tr } = useI18n();
  const [open, setOpen] = useState(false);
  const r = useFetch<CombinedReport>(open ? "/reports/combined/" : null);
  const d = r.data;
  return (
    <details className="card mb-1" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary><b>{t("rep.strength")}</b></summary>
      <p className="muted small">{t("comb.hint")}</p>
      <ErrorNotice error={open ? r.error : null} />
      {open && r.loading && !d ? <Loading /> : null}
      {d && (
        <>
          {d.excludes_restricted_units && <Notice kind="info">{t("comb.restricted")}</Notice>}
          <div className="stat"><span>{t("comb.total")}</span><b>{d.totals.total}</b></div>
          <div className="stat"><span>{t("comb.serving")}</span><b>{d.totals.serving}</b></div>
          {(d.trend ?? []).length >= 2 ? <TrendLine points={d.trend ?? []} /> : <p className="muted small">{t("comb.trendWait")}</p>}
          {d.branches.map((b) => (
            <div key={b.id}>
              {d.branches.length > 1 && <h3>{name(b)}</h3>}
              <div className="stat"><span>{t("comb.units")}</span><b>{b.units}</b></div>
              {Object.keys(b.by_status).length > 0 && <h3>{t("comb.byStatus")}</h3>}
              {Object.entries(b.by_status).map(([k, n]) => (
                <div key={k} className="stat"><span>{t(`pstatus.${k}` as Key)}</span><b>{n}</b></div>
              ))}
              {Object.keys(b.by_rank_category).length > 0 && <h3>{t("comb.byClass")}</h3>}
              {Object.entries(b.by_rank_category).map(([k, n]) => (
                <div key={k} className="stat"><span>{tr(`cat.${k}`) ?? k}</span><b>{n}</b></div>
              ))}
            </div>
          ))}
          <h3>{t("comb.byRegion")}</h3>
          {d.regions.map((g) => (
            <div key={g.region.id} className="stat"><span>{name(g.region)}</span><b>{g.serving}</b></div>
          ))}
          <p className="muted small">{t("comb.generated")}: {formatDate(d.generated_at, lang)}</p>
        </>
      )}
    </details>
  );
}
