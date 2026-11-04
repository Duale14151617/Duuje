import { Link, useParams } from "react-router-dom";
import type { DepartmentProfile as Profile, OrgPerson } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { Holder, StatTiles } from "../components/OrgBits";
import { statusTone } from "../components/status";
import { Chip, ErrorNotice, Loading, Notice, PageHeader } from "../components/ui";
import { useI18n, type Key } from "../i18n";

function People({ rows }: { rows: OrgPerson[] }) {
  const { t, name } = useI18n();
  if (rows.length === 0) return <p className="muted">{t("org2.noPeople")}</p>;
  return (
    <table>
      <thead><tr><th>{t("pers.rank")}</th><th>{t("pers.fullName")}</th><th>{t("pers.serviceNumber")}</th><th>{t("pers.unit")}</th><th>{t("pers.status")}</th></tr></thead>
      <tbody>{rows.map((p) => (
        <tr key={p.id}><td>{p.rank.code} {name(p.rank)}</td><td><Link to={`/personnel/${p.id}`}>{p.full_name}</Link></td><td>{p.service_number ?? "-"}</td>
          <td><Link to={`/units/${p.org_unit.id}`}>{name(p.org_unit)}</Link></td><td><Chip tone={statusTone(p.status)}>{t(`pstatus.${p.status}` as Key)}</Chip></td></tr>
      ))}</tbody>
    </table>
  );
}

/** One department of one unit: leadership, deputy, staff members (assigned to this unit) and assigned personnel (in sub-units). */
export function DepartmentProfile() {
  const { id = "", deptId = "" } = useParams();
  const { t, name } = useI18n();
  const res = useFetch<Profile>(`/organization/units/${id}/departments/${deptId}/`);
  if (res.loading && !res.data) return <Loading />;
  if (res.error || !res.data) return <ErrorNotice error={res.error} />;
  const d = res.data;
  const title = `${name(d.department)} · ${name(d.unit)}`;
  const pdf = () => ({
    title, subtitle: `${t("org2.total")}: ${d.stats.total} · ${t("org2.active")}: ${d.stats.active}`,
    sections: [
      { heading: t("org2.leadership"), columns: [{ header: "", width: 2 }, { header: "", width: 3 }],
        rows: [[t("org2.head"), d.head?.holder ? `${name(d.head.holder.rank)} ${d.head.holder.full_name}` : "-"],
               [t("org2.deputy"), d.deputy?.holder ? `${name(d.deputy.holder.rank)} ${d.deputy.holder.full_name}` : "-"]] },
      { heading: t("org2.staff"), columns: [{ header: t("pers.rank"), width: 2 }, { header: t("pers.fullName"), width: 3 }, { header: t("pers.serviceNumber"), width: 2 }],
        rows: (d.staff ?? []).map((p) => [`${p.rank.code} ${name(p.rank)}`, p.full_name, p.service_number ?? ""]) },
    ],
  });
  return (
    <>
      <p><Link to={`/units/${id}`}>{t("common.back")}</Link></p>
      <PageHeader title={<>{name(d.department)} {d.department.restricted && <Chip tone="draft">{t("dept.restricted")}</Chip>}</>}
        subtitle={<>{t("pers.unit")}: <Link to={`/units/${id}`}>{name(d.unit)}</Link>{!d.established ? <> · <Chip tone="draft">{t("org2.notEstablished")}</Chip></> : null}</>}
        actions={d.staff ? <ExportPdfButton build={pdf} filename={`dept-${d.department.code}-${d.unit.code}`} /> : undefined} />
      {(d.department.description_en || d.department.description_so) && <p className="muted">{name({ name_en: d.department.description_en, name_so: d.department.description_so })}</p>}
      <div className="card"><h2>{t("org2.leadership")}</h2>
        <table><tbody>
          <tr><td>{t("org2.head")}</td><td><Holder office={d.head} /></td></tr>
          <tr><td>{t("org2.deputy")}</td><td><Holder office={d.deputy} /></td></tr>
        </tbody></table>
        {d.can.appoint && <p className="muted">{t("org2.appointHint")}</p>}
      </div>
      <div className="card"><h2>{t("org2.strength")}</h2><StatTiles b={d.stats} extra={[{ label: t("org2.staff"), value: d.staff_total }, { label: t("org2.assigned"), value: d.assigned_total }]} /></div>
      {d.roster_hidden ? <Notice>{t("dept.rosterHidden")}</Notice> : !d.can.name ? <Notice>{t("uo.holderHidden")}</Notice> : (
        <>
          <div className="card"><h2>{t("org2.staff")} ({d.staff_total})</h2><People rows={d.staff ?? []} /></div>
          <div className="card"><h2>{t("org2.assigned")} ({d.assigned_total})</h2><People rows={d.assigned ?? []} /></div>
        </>
      )}
    </>
  );
}
