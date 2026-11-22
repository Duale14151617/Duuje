import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Department, Person } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import { ErrorNotice, Field } from "./ui";

/** Shows a person's department and unit profile link; people who manage the record can change the department (written to history). */
export function PersonDepartment({ person, onSaved }: { person: Person; onSaved: () => void }) {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const departments = useFetch<Department[]>(can("personnel.manage") ? "/organization/departments/" : null);
  const [value, setValue] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const current = person.department?.id ?? "";
  const chosen = value ?? current;

  async function save() {
    setError(null);
    try {
      await api(`/personnel/${person.id}/`, { method: "PATCH", body: { department: chosen || null, version: person.version } });
      setValue(null);
      onSaved();
    } catch (err) { setError(err); }
  }

  return (
    <section className="card">
      <h2>{t("dept.department")}</h2>
      <p>{person.department ? name(person.department) : <span className="muted">{t("dept.unassigned")}</span>}
        {" · "}<Link to={`/units/${person.org_unit.id}`}>{t("dept.openUnitProfile")}</Link></p>
      {can("personnel.manage") && person.status !== "died" && (
        <>
          <ErrorNotice error={error} />
          <Field label={t("dept.change")}>
            <select value={chosen} onChange={(e) => setValue(e.target.value)}>
              <option value="">{t("dept.unassigned")}</option>
              {(departments.data ?? []).map((d) => <option key={d.id} value={d.id}>{name(d)}</option>)}
            </select>
          </Field>
          <button type="button" disabled={chosen === current} onClick={() => void save()}>{t("common.save")}</button>
        </>
      )}
    </section>
  );
}
