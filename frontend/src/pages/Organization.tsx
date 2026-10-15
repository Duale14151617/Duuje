import { useState, type CSSProperties, type FormEvent } from "react";
import { api } from "../api/client";
import type { Branch, Designation, Page, Unit, UnitType } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useUnitTypes } from "../api/useUnitTypes";
import { UnitPicker } from "../components/UnitPicker";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, Loading, Pager } from "../components/ui";
import { useI18n, type Key } from "../i18n";

const PARENT_LEVELS: Record<string, string[]> = {
  region: ["headquarters"], branch_command: ["region"], unit: ["branch_command", "unit"],
};

function TypeField({ level, types, value, onChange }: {
  level: string; types: UnitType[]; value: string; onChange: (v: string) => void }) {
  const { t, name } = useI18n();
  // Taliska Guud is the regional command (a branch command); every other template level is a unit.
  const fits = types.filter((x) => x.active && (x.code === "TALISKA_GUUD") === (level === "branch_command"));
  if (level !== "branch_command" && level !== "unit") return null;
  return (
    <Field label={t("org.type")}>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("org.noType")}</option>
        {fits.map((x) => <option key={x.id} value={x.id}>{name(x)}</option>)}
      </select>
    </Field>
  );
}

function DesignationBoxes({ designations, value, onChange }: {
  designations: Designation[]; value: string[]; onChange: (v: string[]) => void }) {
  const { t, name } = useI18n();
  if (designations.length === 0) return null;
  return (
    <fieldset className="field" style={{ border: 0, padding: 0 }}>
      <legend>{t("org.designations")}</legend>
      <div className="row">
        {designations.filter((d) => d.active || value.includes(d.id)).map((d) => (
          <label key={d.id} className="row">
            <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={value.includes(d.id)}
                   onChange={(e) => onChange(e.target.checked ? [...value, d.id] : value.filter((x) => x !== d.id))} />
            <span>{name(d)}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function UnitEditor({ unit, onDone }: { unit: Unit; onDone: () => void }) {
  const { t } = useI18n();
  const [nameEn, setNameEn] = useState(unit.name_en);
  const [nameSo, setNameSo] = useState(unit.name_so);
  const [active, setActive] = useState(unit.active);
  const [unitType, setUnitType] = useState(unit.unit_type ?? "");
  const [desigs, setDesigs] = useState<string[]>(unit.designations);
  const [exMin, setExMin] = useState(unit.strength_exception_min?.toString() ?? "");
  const [exMax, setExMax] = useState(unit.strength_exception_max?.toString() ?? "");
  const [exNote, setExNote] = useState(unit.strength_exception_note);
  const [error, setError] = useState<unknown>(null);
  const cat = useUnitTypes();

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/organization/units/${unit.id}/`, {
        method: "PATCH", body: {
          name_en: nameEn, name_so: nameSo, active, version: unit.version,
          ...(unit.level === "branch_command" || unit.level === "unit" ? { unit_type: unitType || null } : {}),
          ...(unit.level === "unit" ? { designations: desigs } : {}),
          strength_exception_min: exMin === "" ? null : Number(exMin),
          strength_exception_max: exMax === "" ? null : Number(exMax),
          ...(exMin === "" && exMax === "" ? {} : { strength_exception_note: exNote }) } });
      onDone();
    } catch (err) { setError(err); }
  }
  return (
    <form onSubmit={(e) => void save(e)} style={{ marginTop: ".5rem" }}>
      <ErrorNotice error={error} />
      <Field label={t("org.nameEn")}><input value={nameEn} onChange={(e) => setNameEn(e.target.value)} required /></Field>
      <Field label={t("org.nameSo")}><input value={nameSo} onChange={(e) => setNameSo(e.target.value)} /></Field>
      <TypeField level={unit.level} types={cat.types.data ?? []} value={unitType} onChange={setUnitType} />
      {unit.level === "unit" && <DesignationBoxes designations={cat.designations.data ?? []} value={desigs} onChange={setDesigs} />}
      {(unit.level === "branch_command" || unit.level === "unit") && (
        <fieldset className="field" style={{ border: 0, padding: 0 }}>
          <legend>{t("org.exceptionTitle")}</legend>
          <Field label={t("org.exMin")}><input type="number" min={0} value={exMin} onChange={(e) => setExMin(e.target.value)} /></Field>
          <Field label={t("org.exMax")}><input type="number" min={0} value={exMax} onChange={(e) => setExMax(e.target.value)} /></Field>
          <Field label={t("org.exNote")}><input value={exNote} maxLength={300} onChange={(e) => setExNote(e.target.value)} /></Field>
        </fieldset>
      )}
      <label className="row" style={{ marginBottom: ".75rem" }}>
        <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={active} onChange={(e) => setActive(e.target.checked)} />
        <span>{t("common.active")}</span>
      </label>
      <div className="row">
        <button type="submit">{t("common.save")}</button>
        <button type="button" className="secondary" onClick={onDone}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}

function AddUnit({ branches, onDone }: { branches: Branch[]; onDone: () => void }) {
  const { t, name } = useI18n();
  const [level, setLevel] = useState("unit");
  const [parent, setParent] = useState("");
  const [branch, setBranch] = useState("");
  const [code, setCode] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [nameSo, setNameSo] = useState("");
  const [unitType, setUnitType] = useState("");
  const [desigs, setDesigs] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const cat = useUnitTypes();

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/organization/units/", { method: "POST", body: {
        level, parent: parent || null, branch: level === "branch_command" ? branch || null : null,
        code, name_en: nameEn, name_so: nameSo,
        ...(unitType ? { unit_type: unitType } : {}), ...(level === "unit" && desigs.length ? { designations: desigs } : {}) } });
      onDone();
    } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void save(e)}>
      <h2>{t("org.add")}</h2>
      <ErrorNotice error={error} />
      <Field label={t("org.level")}>
        <select value={level} onChange={(e) => { setLevel(e.target.value); setParent(""); setUnitType(""); }}>
          {Object.keys(PARENT_LEVELS).map((l) => <option key={l} value={l}>{t(`level.${l}` as Key)}</option>)}
        </select>
      </Field>
      <UnitPicker key={level} label={t("org.parent")} value={parent} required
                  params={level === "unit" ? { placeable: 1 } : { placeable: undefined, level: PARENT_LEVELS[level][0] }}
                  onChange={(id) => setParent(id)} />
      {level === "branch_command" && (
        <Field label={t("org.branch")}>
          <select value={branch} onChange={(e) => setBranch(e.target.value)} required>
            <option value="" />
            {branches.map((b) => <option key={b.id} value={b.id}>{name(b)}</option>)}
          </select>
        </Field>
      )}
      <Field label={t("org.code")}><input value={code} onChange={(e) => setCode(e.target.value)} required /></Field>
      <Field label={t("org.nameEn")}><input value={nameEn} onChange={(e) => setNameEn(e.target.value)} required /></Field>
      <Field label={t("org.nameSo")}><input value={nameSo} onChange={(e) => setNameSo(e.target.value)} /></Field>
      <TypeField level={level} types={cat.types.data ?? []} value={unitType} onChange={setUnitType} />
      {level === "unit" && <DesignationBoxes designations={cat.designations.data ?? []} value={desigs} onChange={setDesigs} />}
      <button type="submit">{t("common.create")}</button>
    </form>
  );
}

export function Organization() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const cat = useUnitTypes();
  const units = useFetch<Page<Unit>>("/organization/units/", { page_size: 50, page, q: q.trim(), unit_type: typeFilter });
  const branches = useFetch<Page<Branch>>("/organization/branches/", { page_size: 100 });
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const manage = can("org.manage");
  const done = () => { setEditing(null); setAdding(false); units.reload(); };

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0 }}>{t("org.title")}</h1>
        {manage && !adding && <button onClick={() => setAdding(true)}>{t("org.add")}</button>}
      </div>
      <ErrorNotice error={units.error} />
      {adding && <AddUnit branches={branches.data?.results ?? []} onDone={done} />}
      <div className="card row">
        <Field label={t("common.search")}><input type="search" value={q} maxLength={100} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></Field>
        <Field label={t("org.filterType")}>
          <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}>
            <option value="">{t("common.all")}</option>
            {(cat.types.data ?? []).map((x) => <option key={x.id} value={x.id}>{name(x)}</option>)}
          </select>
        </Field>
      </div>
      {units.loading && !units.data ? <Loading /> : null}
      {units.data && units.data.results.length === 0 && <p>{t("org.noUnits")}</p>}
      <ul className="list">
        {units.data?.results.map((u) => (
          <li key={u.id} className="item indent" style={{ "--d": u.depth } as CSSProperties}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <h2>{name(u)}</h2>
                <span className="muted">{t(`level.${u.level}` as Key)} · {u.code}</span>
                <div className="row" style={{ marginTop: ".25rem" }}>
                  {u.unit_type && cat.typeById.get(u.unit_type) && <Chip tone="ok">{name(cat.typeById.get(u.unit_type)!)}</Chip>}
                  {u.designations.map((id) => cat.designationById.get(id)).filter((d): d is Designation => !!d)
                    .map((d) => <Chip key={d.id}>{name(d)}</Chip>)}
                </div>
              </div>
              <div className="row">
                {!u.active && <Chip tone="bad">{t("common.inactive")}</Chip>}
                {manage && editing !== u.id && <button className="secondary" onClick={() => setEditing(u.id)}>{t("common.edit")}</button>}
              </div>
            </div>
            {editing === u.id && <UnitEditor unit={u} onDone={done} />}
          </li>
        ))}
      </ul>
      <Pager page={page} count={units.data?.count ?? 0} pageSize={50} onPage={setPage} />
      {branches.data && (
        <section className="card">
          <h2>{t("org.branches")}</h2>
          <div className="row">
            {branches.data.results.map((b) => <Chip key={b.id}>{name(b)}</Chip>)}
          </div>
        </section>
      )}
    </>
  );
}
