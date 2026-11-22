import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Department, FormationRoleRow } from "../api/types";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Loading, PageHeader } from "../components/ui";
import { useI18n, type Key } from "../i18n";

const ROLES = ["", "ghq", "regional", "brigade", "battalion"];

/** Structure settings (headquarters): the department catalogue and which unit types are General Headquarters, commands, brigades, battalions. */
export function OrgSettings() {
  const { t, name } = useI18n();
  const depts = useFetch<Department[]>("/organization/departments/", { include_inactive: 1 });
  const roles = useFetch<FormationRoleRow[]>("/organization/formation-roles/");
  const [error, setError] = useState<unknown>(null);
  const [form, setForm] = useState({ code: "", name_en: "", name_so: "", restricted_roster: false });

  async function run(fn: () => Promise<unknown>, after?: () => void) {
    setError(null);
    try { await fn(); depts.reload(); roles.reload(); after?.(); } catch (err) { setError(err); }
  }
  const add = (e: FormEvent) => { e.preventDefault(); void run(() => api("/organization/departments/", { method: "POST", body: form }), () => setForm({ code: "", name_en: "", name_so: "", restricted_roster: false })); };
  const patch = (d: Department, body: Partial<Department>) => run(() => api(`/organization/departments/${d.id}/`, { method: "PATCH", body: { ...body, version: d.version } }));

  return (
    <>
      <PageHeader title={t("org2.settings")} subtitle={t("org2.settingsHint")} />
      <ErrorNotice error={error ?? depts.error ?? roles.error} />
      <div className="card">
        <h2>{t("org2.catalogue")}</h2>
        {depts.loading && !depts.data ? <Loading /> : (
          <table>
            <thead><tr><th>{t("dept.department")}</th><th>{t("org2.code")}</th><th>{t("dept.restricted")}</th><th /></tr></thead>
            <tbody>{(depts.data ?? []).map((d) => (
              <tr key={d.id}>
                <td>{name(d)} {!d.active && <Chip tone="draft">{t("tree.inactive")}</Chip>}</td><td className="muted">{d.code}</td>
                <td><input type="checkbox" checked={d.restricted_roster} aria-label={t("dept.restricted")} onChange={(e) => void patch(d, { restricted_roster: e.target.checked })} /></td>
                <td><button type="button" className="secondary sm" onClick={() => void patch(d, { active: !d.active })}>{d.active ? t("org2.retire") : t("org2.reactivate")}</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
        <form onSubmit={add}>
          <h3>{t("org2.addDepartment")}</h3>
          <Field label={t("org2.code")}><input value={form.code} required maxLength={32} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
          <Field label="English"><input value={form.name_en} required maxLength={100} onChange={(e) => setForm({ ...form, name_en: e.target.value })} /></Field>
          <Field label="Somali"><input value={form.name_so} maxLength={100} onChange={(e) => setForm({ ...form, name_so: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={form.restricted_roster} onChange={(e) => setForm({ ...form, restricted_roster: e.target.checked })} /><span>{t("dept.restricted")}</span></label>
          <div className="row"><button type="submit">{t("common.create")}</button></div>
        </form>
      </div>
      <div className="card">
        <h2>{t("org2.formationRoles")}</h2>
        <p className="muted">{t("org2.formationHint")}</p>
        <table><tbody>{(roles.data ?? []).filter((r) => r.active).map((r) => (
          <tr key={r.id}><td>{name(r)} <span className="muted">{r.code}</span></td>
            <td><select value={r.formation_role} aria-label={name(r)}
                        onChange={(e) => void run(() => api(`/organization/formation-roles/${r.id}/`, { method: "PATCH", body: { formation_role: e.target.value, version: r.version } }))}>
              {ROLES.map((x) => <option key={x} value={x}>{x ? t(`org2.role.${x}` as Key) : t("org2.role.none")}</option>)}
            </select></td></tr>
        ))}</tbody></table>
      </div>
    </>
  );
}
