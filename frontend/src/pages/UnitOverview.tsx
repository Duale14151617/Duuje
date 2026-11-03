import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { UnitOverview as Overview } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { UnitPicker } from "../components/UnitPicker";
import { Chip, ErrorNotice, Loading, Notice } from "../components/ui";
import { useI18n } from "../i18n";

/** Pick any Guuto, Urur or section, then open its overview. */
export function UnitsHome() {
  const { t } = useI18n();
  const nav = useNavigate();
  const [id, setId] = useState("");
  return (
    <main>
      <h1>{t("uo.title")}</h1>
      <div className="card">
        <UnitPicker label={t("uo.pick")} value={id} onChange={(v) => { setId(v); if (v) nav(`/units/${v}`); }} />
      </div>
    </main>
  );
}

/** Read-only overview of one unit: strength counted once, sub-units, command appointments, printable PDF. */
export function UnitOverview() {
  const { id } = useParams();
  const { t, name, lang } = useI18n();
  const res = useFetch<Overview>(id ? `/organization/units/${id}/overview/` : null);
  if (res.loading) return <main><Loading /></main>;
  if (res.error || !res.data) return <main><ErrorNotice error={res.error} /></main>;
  const o = res.data;
  const title = name(o.unit);

  const pdf = () => ({
    title, subtitle: `${o.unit.code} · ${t("uo.strength")}: ${o.strength.total}`,
    sections: [
      { heading: t("uo.strength"), columns: [{ header: t("uo.direct"), width: 1 }, { header: t("uo.total"), width: 1 }],
        rows: [[String(o.strength.direct), String(o.strength.total)]] },
      { heading: t("uo.subunits"), columns: [{ header: "", width: 3 }, { header: t("uo.direct"), width: 1, align: "right" as const }, { header: t("uo.total"), width: 1, align: "right" as const }],
        rows: o.children.map((c) => [`${name(c)} (${c.code})`, String(c.direct), String(c.total)]) },
      { heading: t("uo.commanders"), columns: [{ header: "", width: 2 }, { header: "", width: 3 }],
        rows: o.commanders.map((c) => [`${lang === "so" && c.type_so ? c.type_so : c.type_en} (${c.unit_code})`, c.holder ? `${c.holder.rank} ${c.holder.full_name}` : "-"]) },
    ],
  });

  return (
    <main>
      <p className="muted">
        {o.breadcrumb.map((b) => <span key={b.id}><Link to={`/units/${b.id}`}>{name(b)}</Link> › </span>)}
      </p>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>{title} <Chip>{o.unit.unit_type ?? o.unit.level}</Chip></h1>
        <ExportPdfButton build={pdf} filename={`unit-${o.unit.code}`} />
      </div>
      {!o.counts_complete && <Notice>{t("uo.noCounts")}</Notice>}
      <div className="card">
        <h2>{t("uo.strength")}</h2>
        <p><strong>{o.strength.total}</strong> · {t("uo.total")}</p>
        <p className="muted">{t("uo.direct")}: {o.strength.direct}</p>
        {Object.keys(o.strength.by_status).length > 0 && (
          <p className="muted">{t("uo.byStatus")}: {Object.entries(o.strength.by_status).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>
        )}
      </div>
      <div className="card">
        <h2>{t("uo.subunits")}</h2>
        {o.children.length === 0 ? <p className="muted">{t("uo.noSubunits")}</p> : (
          <table>
            <thead><tr><th></th><th>{t("uo.direct")}</th><th>{t("uo.total")}</th></tr></thead>
            <tbody>{o.children.map((c) => (
              <tr key={c.id}><td><Link to={`/units/${c.id}`}>{name(c)}</Link> <span className="muted">{c.code}</span></td><td>{c.direct}</td><td>{c.total}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <div className="card">
        <h2>{t("uo.commanders")}</h2>
        {o.commanders.length === 0 ? <p className="muted">{t("uo.noCommanders")}</p> : (
          <table>
            <tbody>{o.commanders.map((c) => (
              <tr key={c.appointment}>
                <td>{lang === "so" && c.type_so ? c.type_so : c.type_en} <span className="muted">{c.unit_code}</span></td>
                <td>{c.holder ? `${c.holder.rank} ${c.holder.full_name}` : <span className="muted">{t("uo.holderHidden")}</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      {o.members.length > 0 && (
        <div className="card">
          <h2>{t("uo.members")} ({o.members.length})</h2>
          <table>
            <tbody>{o.members.map((m) => (
              <tr key={m.id}><td>{m.rank}</td><td>{m.full_name}</td><td className="muted">{m.service_number ?? "-"}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </main>
  );
}
