import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Designation, DesignationRule, Finding, Page, StrengthStatus, StructureRow, UnitType } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, Loading, Pager } from "../components/ui";
import { useI18n, type Key } from "../i18n";

const TONE: Record<StrengthStatus, string> = { no_reference: "", unknown: "", below: "warn", within: "ok", above: "warn" };
const num = (v: string) => (v === "" ? null : Number(v));
const range = (lo: number | null, hi: number | null) =>
  lo == null && hi == null ? "—" : lo === hi ? String(lo) : `${lo ?? "…"}–${hi ?? "…"}`;

function Findings() {
  const { t, name } = useI18n();
  const f = useFetch<{ count: number; truncated: boolean; results: Finding[] }>("/organization/structure/findings/");
  const types = useFetch<UnitType[]>("/organization/unit-types/");
  const desig = useFetch<Designation[]>("/organization/designations/");
  const typeName = (code?: string) => { const x = types.data?.find((y) => y.code === code); return x ? name(x) : code ?? ""; };
  const desigName = (code?: string) => { const x = desig.data?.find((y) => y.code === code); return x ? name(x) : code ?? ""; };
  return (
    <section className="card">
      <h2>{t("struct.findings")}</h2>
      <ErrorNotice error={f.error} />
      {f.loading && !f.data ? <Loading /> : null}
      {f.data && f.data.count === 0 && <p className="muted">{t("struct.noFindings")}</p>}
      <ul className="list">
        {f.data?.results.map((x, i) => (
          <li key={i} className="item">
            {t(`finding.${x.code}` as Key, {
              unit: name(x.unit), type: typeName(x.type), expected: x.expected ?? "", actual: x.actual ?? "",
              parent_type: typeName(x.parent_type), child_type: typeName(x.child_type), designation: desigName(x.designation) })}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Strength() {
  const { t, name } = useI18n();
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const types = useFetch<UnitType[]>("/organization/unit-types/");
  const rows = useFetch<Page<StructureRow>>("/organization/structure/", { type, page, page_size: 50 });
  const typeOf = (id: string) => types.data?.find((x) => x.id === id);
  return (
    <section className="card">
      <h2>{t("struct.units")}</h2>
      <p className="muted">{t("struct.note")}</p>
      <Field label={t("org.filterType")}>
        <select value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
          <option value="">{t("common.all")}</option>
          {types.data?.map((x) => <option key={x.id} value={x.code}>{name(x)}</option>)}
        </select>
      </Field>
      <ErrorNotice error={rows.error} />
      {rows.loading && !rows.data ? <Loading /> : null}
      {rows.data && rows.data.results.length === 0 && <p>{t("struct.noUnits")}</p>}
      <ul className="list">
        {rows.data?.results.map((r) => (
          <li key={r.id} className="item">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <h3 style={{ margin: 0 }}>{name(r)}</h3>
                <span className="muted">{typeOf(r.unit_type) ? name(typeOf(r.unit_type)!) : ""} · {r.code}</span>
              </div>
              <Chip tone={TONE[r.strength_status]}>{t(`status.${r.strength_status}` as Key)}</Chip>
            </div>
            <div className="row muted">
              <span>{t("struct.reference")}: {range(r.reference_min, r.reference_max)}</span>
              <span>{t("struct.actual")}: {r.actual_strength ?? "—"}</span>
              {r.has_exception && <Chip>{t("struct.exception")}</Chip>}
            </div>
            {r.has_exception && r.strength_exception_note && <p className="muted" style={{ margin: ".25rem 0 0" }}>{r.strength_exception_note}</p>}
          </li>
        ))}
      </ul>
      <Pager page={page} count={rows.data?.count ?? 0} pageSize={50} onPage={setPage} />
    </section>
  );
}

function TypeForm({ item, types, onDone }: { item?: UnitType; types: UnitType[]; onDone: () => void }) {
  const { t, name } = useI18n();
  const [f, setF] = useState({
    code: item?.code ?? "", name_en: item?.name_en ?? "", name_so: item?.name_so ?? "", tier: item?.tier.toString() ?? "",
    parent_type: item?.parent_type ?? "", per: item?.standard_per_parent?.toString() ?? "",
    min: item?.reference_min?.toString() ?? "", max: item?.reference_max?.toString() ?? "",
    desc: item?.description_en ?? "", active: item?.active ?? true });
  const [error, setError] = useState<unknown>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save(e: FormEvent) {
    e.preventDefault();
    const body = { name_en: f.name_en, name_so: f.name_so, tier: Number(f.tier), parent_type: f.parent_type || null,
      standard_per_parent: num(f.per), reference_min: num(f.min), reference_max: num(f.max), description_en: f.desc, active: f.active };
    try {
      if (item) await api(`/organization/unit-types/${item.id}/`, { method: "PATCH", body: { ...body, version: item.version } });
      else await api("/organization/unit-types/", { method: "POST", body: { ...body, code: f.code } });
      onDone();
    } catch (err) { setError(err); }
  }
  return (
    <form onSubmit={(e) => void save(e)} className={item ? "" : "card"}>
      <ErrorNotice error={error} />
      {!item && <Field label={t("org.code")}><input value={f.code} onChange={set("code")} required maxLength={32} /></Field>}
      <Field label={t("org.nameEn")}><input value={f.name_en} onChange={set("name_en")} required /></Field>
      <Field label={t("org.nameSo")}><input value={f.name_so} onChange={set("name_so")} /></Field>
      <Field label={t("types.tier")}><input type="number" min={1} value={f.tier} onChange={set("tier")} required /></Field>
      <Field label={t("types.parent")}>
        <select value={f.parent_type} onChange={set("parent_type")}>
          <option value="" />
          {types.filter((x) => x.id !== item?.id).map((x) => <option key={x.id} value={x.id}>{name(x)}</option>)}
        </select>
      </Field>
      <Field label={t("types.perParent")}><input type="number" min={1} value={f.per} onChange={set("per")} /></Field>
      <Field label={t("types.refMin")}><input type="number" min={0} value={f.min} onChange={set("min")} /></Field>
      <Field label={t("types.refMax")}><input type="number" min={0} value={f.max} onChange={set("max")} /></Field>
      <Field label={t("types.description")}><input value={f.desc} onChange={set("desc")} maxLength={200} /></Field>
      {item && (
        <label className="row" style={{ marginBottom: ".75rem" }}>
          <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />
          <span>{t("common.active")}</span>
        </label>
      )}
      <div className="row">
        <button type="submit">{item ? t("common.save") : t("common.create")}</button>
        <button type="button" className="secondary" onClick={onDone}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}

function DesignationForm({ item, onDone }: { item?: Designation; onDone: () => void }) {
  const { t } = useI18n();
  const [f, setF] = useState({ code: item?.code ?? "", name_en: item?.name_en ?? "", name_so: item?.name_so ?? "",
    desc: item?.description_en ?? "", active: item?.active ?? true });
  const [error, setError] = useState<unknown>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save(e: FormEvent) {
    e.preventDefault();
    const body = { name_en: f.name_en, name_so: f.name_so, description_en: f.desc, active: f.active };
    try {
      if (item) await api(`/organization/designations/${item.id}/`, { method: "PATCH", body: { ...body, version: item.version } });
      else await api("/organization/designations/", { method: "POST", body: { ...body, code: f.code } });
      onDone();
    } catch (err) { setError(err); }
  }
  return (
    <form onSubmit={(e) => void save(e)} className={item ? "" : "card"}>
      <ErrorNotice error={error} />
      {!item && <Field label={t("org.code")}><input value={f.code} onChange={set("code")} required maxLength={32} /></Field>}
      <Field label={t("org.nameEn")}><input value={f.name_en} onChange={set("name_en")} required /></Field>
      <Field label={t("org.nameSo")}><input value={f.name_so} onChange={set("name_so")} /></Field>
      <Field label={t("desig.description")}><input value={f.desc} onChange={set("desc")} maxLength={200} /></Field>
      {item && (
        <label className="row" style={{ marginBottom: ".75rem" }}>
          <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />
          <span>{t("common.active")}</span>
        </label>
      )}
      <div className="row">
        <button type="submit">{item ? t("common.save") : t("common.create")}</button>
        <button type="button" className="secondary" onClick={onDone}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}

function Catalogues() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const manage = can("org.manage");
  const types = useFetch<UnitType[]>("/organization/unit-types/");
  const desig = useFetch<Designation[]>("/organization/designations/");
  const rules = useFetch<DesignationRule[]>("/organization/designation-rules/");
  const [editType, setEditType] = useState<string | null>(null);
  const [editDesig, setEditDesig] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const tn = (id: string) => { const x = types.data?.find((y) => y.id === id); return x ? name(x) : ""; };
  const dn = (id: string) => { const x = desig.data?.find((y) => y.id === id); return x ? name(x) : ""; };
  const doneT = () => { setEditType(null); types.reload(); };
  const doneD = () => { setEditDesig(null); desig.reload(); };
  async function toggleRule(r: DesignationRule) {
    try { await api(`/organization/designation-rules/${r.id}/`, { method: "PATCH", body: { active: !r.active, version: r.version } }); rules.reload(); }
    catch (err) { setError(err); }
  }
  return (
    <>
      <section className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>{t("types.title")}</h2>
          {manage && editType !== "new" && <button onClick={() => setEditType("new")}>{t("types.add")}</button>}
        </div>
        <ErrorNotice error={types.error ?? error} />
        {editType === "new" && <TypeForm types={types.data ?? []} onDone={doneT} />}
        <ul className="list">
          {types.data?.map((x) => (
            <li key={x.id} className="item">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <h3 style={{ margin: 0 }}>{x.tier}. {name(x)}</h3>
                  <span className="muted">
                    {x.code}{x.parent_type ? ` · ${tn(x.parent_type)}` : ""} · {t("struct.reference")}: {range(x.reference_min, x.reference_max)}
                    {x.standard_per_parent ? ` · ×${x.standard_per_parent}` : ""}{x.description_en ? ` · ${x.description_en}` : ""}
                  </span>
                </div>
                <div className="row">
                  {!x.active && <Chip tone="bad">{t("common.inactive")}</Chip>}
                  {manage && editType !== x.id && <button className="secondary" onClick={() => setEditType(x.id)}>{t("common.edit")}</button>}
                </div>
              </div>
              {editType === x.id && <TypeForm item={x} types={types.data ?? []} onDone={doneT} />}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>{t("desig.title")}</h2>
          {manage && editDesig !== "new" && <button onClick={() => setEditDesig("new")}>{t("desig.add")}</button>}
        </div>
        <p className="muted">{t("desig.notRank")}</p>
        {editDesig === "new" && <DesignationForm onDone={doneD} />}
        <ul className="list">
          {desig.data?.map((x) => (
            <li key={x.id} className="item">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <h3 style={{ margin: 0 }}>{name(x)}</h3>
                  <span className="muted">{x.code}{x.description_en ? ` · ${x.description_en}` : ""}</span>
                </div>
                <div className="row">
                  {!x.active && <Chip tone="bad">{t("common.inactive")}</Chip>}
                  {manage && editDesig !== x.id && <button className="secondary" onClick={() => setEditDesig(x.id)}>{t("common.edit")}</button>}
                </div>
              </div>
              {editDesig === x.id && <DesignationForm item={x} onDone={doneD} />}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>{t("rules.title")}</h2>
        <p className="muted">{t("rules.note")}</p>
        <ul className="list">
          {rules.data?.map((r) => (
            <li key={r.id} className="item">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>{t("rules.sentence", { parent: tn(r.parent_type), child: tn(r.child_type), designation: dn(r.designation) })}</span>
                <div className="row">
                  {!r.active && <Chip tone="bad">{t("common.inactive")}</Chip>}
                  {manage && <button className="secondary" onClick={() => void toggleRule(r)}>{r.active ? t("common.deactivate") : t("common.activate")}</button>}
                </div>
              </div>
              {r.note && <p className="muted" style={{ margin: ".25rem 0 0" }}>{r.note}</p>}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

export function Structure() {
  const { t } = useI18n();
  return (
    <>
      <h1>{t("struct.title")}</h1>
      <Findings />
      <Strength />
      <Catalogues />
    </>
  );
}
