import { useState } from "react";
import type { CombinedReport } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ErrorNotice, Loading, Notice, formatDate } from "./ui";
import { useI18n, type Key } from "../i18n";

/** Army strength for the reports page. Aggregates only. The figures are loaded only when the card is opened, because the server audits every view. */
export function ArmyStrength() {
  const { t, lang, name, tr } = useI18n();
  const [open, setOpen] = useState(false);
  const r = useFetch<CombinedReport>(open ? "/reports/combined/" : null);
  const d = r.data;
  return (
    <details className="card" style={{ marginBottom: "1rem" }} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary><b>{t("rep.strength")}</b></summary>
      <p className="muted small">{t("comb.hint")}</p>
      <ErrorNotice error={open ? r.error : null} />
      {open && r.loading && !d ? <Loading /> : null}
      {d && (
        <>
          {d.excludes_restricted_units && <Notice kind="info">{t("comb.restricted")}</Notice>}
          <div className="stat"><span>{t("comb.total")}</span><b>{d.totals.total}</b></div>
          <div className="stat"><span>{t("comb.serving")}</span><b>{d.totals.serving}</b></div>
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
