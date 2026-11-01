import type { CombinedReport as Data } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ErrorNotice, Loading, Notice, formatDate } from "../components/ui";
import { useI18n, type Key } from "../i18n";

/** Army and Navy strength side by side. Aggregates only; the server audits every view. */
export function CombinedReport() {
  const { t, lang, name, tr } = useI18n();
  const r = useFetch<Data>("/reports/combined/");
  const d = r.data;
  return (
    <>
      <h1>{t("comb.title")}</h1>
      <p className="muted">{t("comb.hint")}</p>
      <ErrorNotice error={r.error} />
      {r.loading && !d ? <Loading /> : null}
      {d && (
        <>
          {d.excludes_restricted_units && <Notice kind="info">{t("comb.restricted")}</Notice>}
          <section className="card">
            <div className="stat"><span>{t("comb.total")}</span><b>{d.totals.total}</b></div>
            <div className="stat"><span>{t("comb.serving")}</span><b>{d.totals.serving}</b></div>
            <p className="muted small">{t("comb.generated")}: {formatDate(d.generated_at, lang)}</p>
          </section>
          {d.branches.map((b) => (
            <section key={b.id} className="card">
              <h2>{name(b)}</h2>
              <div className="stat"><span>{t("comb.total")}</span><b>{b.total}</b></div>
              <div className="stat"><span>{t("comb.serving")}</span><b>{b.serving}</b></div>
              <div className="stat"><span>{t("comb.units")}</span><b>{b.units}</b></div>
              {Object.keys(b.by_status).length > 0 && <h3>{t("comb.byStatus")}</h3>}
              {Object.entries(b.by_status).map(([k, n]) => (
                <div key={k} className="stat"><span>{t(`pstatus.${k}` as Key)}</span><b>{n}</b></div>
              ))}
              {Object.keys(b.by_rank_category).length > 0 && <h3>{t("comb.byClass")}</h3>}
              {Object.entries(b.by_rank_category).map(([k, n]) => (
                <div key={k} className="stat"><span>{tr(`cat.${k}`) ?? k}</span><b>{n}</b></div>
              ))}
            </section>
          ))}
          <section className="card">
            <h2>{t("comb.byRegion")}</h2>
            {d.regions.map((g) => (
              <div key={g.region.id} className="stat">
                <span>{name(g.region)} <span className="muted">({Object.entries(g.serving_by_branch).map(([c, n]) => `${c} ${n}`).join(" · ")})</span></span>
                <b>{g.serving}</b>
              </div>
            ))}
          </section>
        </>
      )}
    </>
  );
}
