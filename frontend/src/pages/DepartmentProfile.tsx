import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AppointmentTypeOut, DepartmentProfile as Profile, OrgOffice, OrgPerson, Page, Person } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { Holder, StatTiles } from "../components/OrgBits";
import { statusTone } from "../components/status";
import { Chip, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";
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

/** Head or deputy of this department: shows the holder, lets an authorized user end the appointment, or appoint someone when vacant. */
function OfficeRow({ role, office, unitId, deptId, canAppoint, onDone }: {
  role: "department_head" | "department_deputy"; office: OrgOffice | null; unitId: string; deptId: string; canAppoint: boolean; onDone: () => void;
}) {
  const { t } = useI18n();
  const types = useFetch<{ results: AppointmentTypeOut[] }>(canAppoint ? "/personnel/appointment-types/" : null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState("");
  const [from, setFrom] = useState(new Date().toISOString().slice(0, 10));
  const [ref, setRef] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const found = useFetch<Page<Person>>(open && q.trim().length >= 2 ? "/personnel/" : null, { q: q.trim(), org_unit: unitId });
  const type = (types.data?.results ?? []).find((x) => x.role === role);
  const label = t(role === "department_head" ? "org2.head" : "org2.deputy");

  async function run(fn: () => Promise<unknown>) {
    setError(null); setBusy(true);
    try { await fn(); setOpen(false); setPick(""); setQ(""); setReason(""); onDone(); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const appoint = () => run(() => api(`/personnel/${pick}/appointments/add/`, { method: "POST", body: {
    org_unit: unitId, appointment_type: type?.id, department: deptId, effective_from: from, authority_ref: ref } }));
  const end = () => run(() => api(`/personnel/${office?.holder?.id}/appointments/${office?.id}/end/`, { method: "POST", body: { reason } }));

  return (
    <>
      <tr>
        <td>{label}</td><td><Holder office={office} /></td>
        <td>{canAppoint && (office
          ? (office.holder && <button type="button" className="secondary sm" onClick={() => setOpen(!open)}>{t("org2.endAppointment")}</button>)
          : <button type="button" className="sm" disabled={!type} onClick={() => setOpen(!open)}>{t("org2.appoint")}</button>)}</td>
      </tr>
      {open && (
        <tr><td colSpan={3}>
          <ErrorNotice error={error} />
          {office ? (
            <>
              <Field label={t("appt.reason")}><input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} /></Field>
              <button type="button" disabled={busy || !reason.trim()} onClick={() => void end()}>{t("org2.endAppointment")}</button>
            </>
          ) : (
            <>
              <Field label={t("org2.findPerson")}><input value={q} onChange={(e) => { setQ(e.target.value); setPick(""); }} /></Field>
              {q.trim().length >= 2 && (
                <select value={pick} aria-label={t("org2.findPerson")} onChange={(e) => setPick(e.target.value)}>
                  <option value="">—</option>
                  {(found.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.rank.code} {p.full_name}{p.service_number ? ` (${p.service_number})` : ""}</option>)}
                </select>
              )}
              <Field label={t("appt.from")}><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
              <Field label={t("appt.authority")}><input value={ref} maxLength={150} onChange={(e) => setRef(e.target.value)} /></Field>
              <button type="button" disabled={busy || !pick || !type} onClick={() => void appoint()}>{t("org2.appoint")}</button>
            </>
          )}
        </td></tr>
      )}
    </>
  );
}

/** One department of one unit: leadership, deputy, staff members (assigned to this unit) and assigned personnel (in sub-units). */
export function DepartmentProfile() {
  const { id = "", deptId = "" } = useParams();
  const { t, name } = useI18n();
  const { can } = useAuth();
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
        actions={<>
          {can("personnel.import") && d.established && (
            <Link className="btn secondary" to={`/personnel/import?unit=${encodeURIComponent(d.unit.code)}&department=${encodeURIComponent(d.department.code)}`}>{t("org2.importPersonnel")}</Link>
          )}
          {d.staff ? <ExportPdfButton build={pdf} filename={`dept-${d.department.code}-${d.unit.code}`} /> : null}
        </>} />
      {(d.department.description_en || d.department.description_so) && <p className="muted">{name({ name_en: d.department.description_en, name_so: d.department.description_so })}</p>}
      <div className="card"><h2>{t("org2.leadership")}</h2>
        <table><tbody>
          <OfficeRow role="department_head" office={d.head} unitId={id} deptId={deptId} canAppoint={d.can.appoint && d.established} onDone={res.reload} />
          <OfficeRow role="department_deputy" office={d.deputy} unitId={id} deptId={deptId} canAppoint={d.can.appoint && d.established} onDone={res.reload} />
        </tbody></table>
        {d.can.appoint && !d.established && <p className="muted">{t("org2.notEstablished")}</p>}
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
