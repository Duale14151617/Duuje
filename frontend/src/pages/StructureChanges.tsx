import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Page, StructureChange, StructureOp, UnitType } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice, Pager } from "../components/ui";
import { useI18n, type Key } from "../i18n";

interface Row {
  code: string; isNew: boolean; name_en: string; name_so: string; tier: string; parent_type: string;
  standard_per_parent: string; reference_min: string; reference_max: string; active: boolean;
}

const num = (v: string): number | null => (v.trim() === "" ? null : Number(v));
const fromType = (t: UnitType, parentCode: string): Row => ({
  code: t.code, isNew: false, name_en: t.name_en, name_so: t.name_so, tier: String(t.tier), parent_type: parentCode,
  standard_per_parent: t.standard_per_parent == null ? "" : String(t.standard_per_parent),
  reference_min: t.reference_min == null ? "" : String(t.reference_min), reference_max: t.reference_max == null ? "" : String(t.reference_max),
  active: t.active,
});

/** Turn the edited rows into operations: only what actually changed is sent. */
function diff(rows: Row[], original: Row[]): StructureOp[] {
  const before = new Map(original.map((r) => [r.code, r]));
  const ops: StructureOp[] = [];
  for (const r of rows) {
    const body = {
      name_en: r.name_en, name_so: r.name_so, tier: Number(r.tier), parent_type: r.parent_type || null,
      standard_per_parent: num(r.standard_per_parent), reference_min: num(r.reference_min), reference_max: num(r.reference_max),
    };
    if (r.isNew) { ops.push({ op: "create", code: r.code.trim().toUpperCase(), ...body }); continue; }
    const o = before.get(r.code);
    if (!o) continue;
    const ob = {
      name_en: o.name_en, name_so: o.name_so, tier: Number(o.tier), parent_type: o.parent_type || null,
      standard_per_parent: num(o.standard_per_parent), reference_min: num(o.reference_min), reference_max: num(o.reference_max),
    };
    const fields: Record<string, unknown> = {};
    for (const k of Object.keys(body) as (keyof typeof body)[]) if (body[k] !== ob[k]) fields[k] = body[k];
    if (r.active !== o.active) fields.active = r.active;
    if (Object.keys(fields).length) ops.push({ op: "update", code: r.code, fields });
  }
  return ops;
}

function Editor({ types, onSaved, onCancel }: { types: UnitType[]; onSaved: () => void; onCancel: () => void }) {
  const { t } = useI18n();
  const byId = useMemo(() => new Map(types.map((x) => [x.id, x.code])), [types]);
  const original = useMemo(() => types.map((x) => fromType(x, x.parent_type ? byId.get(x.parent_type) ?? "" : "")), [types, byId]);
  const [rows, setRows] = useState<Row[]>(original);
  const [title, setTitle] = useState("");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [empty, setEmpty] = useState(false);
  const set = (i: number, patch: Partial<Row>) => setRows((cur) => cur.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const codes = rows.map((r) => r.code.trim().toUpperCase()).filter(Boolean);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null); setEmpty(false);
    const operations = diff(rows, original);
    if (operations.length === 0) { setEmpty(true); return; }
    try { await api("/organization/structure-changes/", { method: "POST", body: { title, rationale, operations } }); onSaved(); }
    catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void save(e)}>
      <h2>{t("sc.new")}</h2>
      <ErrorNotice error={error} />
      {empty && <Notice kind="error">{t("sc.noChanges")}</Notice>}
      <Field label={t("sc.proposalTitle")}><input value={title} maxLength={150} onChange={(e) => setTitle(e.target.value)} required /></Field>
      <Field label={t("sc.rationale")}><textarea value={rationale} rows={3} onChange={(e) => setRationale(e.target.value)} /></Field>
      <h3>{t("sc.levels")}</h3>
      {rows.map((r, i) => (
        <fieldset key={i}>
          <legend>{r.isNew ? t("sc.addLevel") : r.code}</legend>
          {r.isNew && <Field label={t("sc.code")}><input value={r.code} maxLength={32} onChange={(e) => set(i, { code: e.target.value })} required /></Field>}
          <div className="grid">
            <Field label={t("sc.nameEn")}><input value={r.name_en} onChange={(e) => set(i, { name_en: e.target.value })} required /></Field>
            <Field label={t("sc.nameSo")}><input value={r.name_so} onChange={(e) => set(i, { name_so: e.target.value })} /></Field>
            <Field label={t("sc.tier")}><input type="number" min={1} value={r.tier} onChange={(e) => set(i, { tier: e.target.value })} required /></Field>
            <Field label={t("sc.parent")}>
              <select value={r.parent_type} onChange={(e) => set(i, { parent_type: e.target.value })}>
                <option value="">{t("sc.noParent")}</option>
                {codes.filter((c) => c !== r.code.trim().toUpperCase()).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label={t("sc.perParent")}><input type="number" min={0} value={r.standard_per_parent} onChange={(e) => set(i, { standard_per_parent: e.target.value })} /></Field>
            <Field label={t("sc.min")}><input type="number" min={0} value={r.reference_min} onChange={(e) => set(i, { reference_min: e.target.value })} /></Field>
            <Field label={t("sc.max")}><input type="number" min={0} value={r.reference_max} onChange={(e) => set(i, { reference_max: e.target.value })} /></Field>
            {!r.isNew && (
              <label className="row"><input type="checkbox" checked={r.active} onChange={(e) => set(i, { active: e.target.checked })} />{t("sc.active")}</label>
            )}
          </div>
        </fieldset>
      ))}
      <div className="row">
        <button type="button" className="secondary" onClick={() => setRows([...rows, { code: "", isNew: true, name_en: "", name_so: "", tier: String(Math.max(0, ...rows.map((r) => Number(r.tier) || 0)) + 1), parent_type: "", standard_per_parent: "", reference_min: "", reference_max: "", active: true }])}>{t("sc.addLevel")}</button>
        <button type="submit">{t("sc.save")}</button>
        <button type="button" className="secondary" onClick={onCancel}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}

function problemText(p: { code: string; type?: string; count?: number }, tr: (k: string) => string | undefined, t: ReturnType<typeof useI18n>["t"]): string {
  if (p.code === "existing_units_conflict") return t("sc.problem.existing_units_conflict", { n: p.count ?? 0 });
  const text = tr(`sc.problem.${p.code}`) ?? tr(`err.${p.code}`) ?? p.code;
  return p.type ? `${p.type}: ${text}` : text;
}

function Card({ c, onChanged }: { c: StructureChange; onChanged: () => void }) {
  const { t, tr, lang } = useI18n();
  const { me, can } = useAuth();
  const [error, setError] = useState<unknown>(null);
  const [reason, setReason] = useState("");
  const mine = me?.id !== undefined && c.proposed_by_username === me.username;
  const problems = c.impact.errors ?? [];

  async function post(action: string, body: Record<string, unknown> = {}) {
    setError(null);
    try { await api(`/organization/structure-changes/${c.id}/${action}/`, { method: "POST", body: { version: c.version, ...body } }); onChanged(); }
    catch (err) { setError(err); }
  }
  return (
    <li className="item">
      <h2>{c.title}</h2>
      <div className="row">
        <Chip tone={c.status === "approved" ? "approved" : c.status === "rejected" ? "bad" : "draft"}>{t(`sc.status.${c.status}` as Key)}</Chip>
        <span className="muted">{t("sc.ops", { n: c.operations.length })} · {t("sc.by", { name: c.proposed_by_username })} · {formatDate(c.created_at, lang)}</span>
      </div>
      {c.rationale && <p>{c.rationale}</p>}
      <p className="muted">{c.operations.map((o) => `${o.op} ${o.code}`).join(", ")}</p>
      {c.impact.affected_units !== undefined && <p className="muted">{t("sc.affected", { n: c.impact.affected_units })}</p>}
      {problems.length > 0 && (
        <Notice kind="error"><strong>{t("sc.problems")}</strong><ul>{problems.map((p, i) => <li key={i}>{problemText(p, tr, t)}</li>)}</ul></Notice>
      )}
      {c.decided_by_username && <p className="muted">{t("sc.decidedBy", { name: c.decided_by_username })}{c.decision_note ? ` — ${c.decision_note}` : ""}</p>}
      <ErrorNotice error={error} />
      <div className="row">
        {c.status === "draft" && mine && can("org.structure_propose") && <button onClick={() => void post("submit")} disabled={problems.length > 0}>{t("sc.submit")}</button>}
        {c.status === "submitted" && can("org.structure_approve") && !mine && (
          <>
            <button onClick={() => { if (window.confirm(t("sc.confirmApprove"))) void post("approve"); }}>{t("sc.approve")}</button>
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("sc.rejectReason")} aria-label={t("sc.rejectReason")} maxLength={500} />
            <button className="secondary" onClick={() => void post("reject", { note: reason })}>{t("sc.reject")}</button>
          </>
        )}
      </div>
    </li>
  );
}

export function StructureChanges() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState(false);
  const list = useFetch<Page<StructureChange>>("/organization/structure-changes/", { page });
  const types = useFetch<UnitType[]>("/organization/unit-types/");
  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0 }}>{t("sc.title")}</h1>
        {can("org.structure_propose") && !editing && types.data && <button onClick={() => setEditing(true)}>{t("sc.new")}</button>}
      </div>
      <Notice>{t("sc.note")}</Notice>
      {editing && types.data && <Editor types={types.data} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); list.reload(); }} />}
      <ErrorNotice error={list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <p>{t("sc.none")}</p>}
      <ul className="list">{list.data?.results.map((c) => <Card key={c.id} c={c} onChanged={list.reload} />)}</ul>
      {list.data && <Pager page={page} count={list.data.count} pageSize={25} onPage={setPage} />}
    </>
  );
}
