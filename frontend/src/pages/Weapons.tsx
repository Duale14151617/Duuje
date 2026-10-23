import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n, type Key } from "../i18n";

interface Named { id?: string; code: string; name_en: string; name_so: string }
interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface Person { id: string; full_name: string; service_number: string | null; status?: string; rank: Named; unit?: UnitB }
interface Custody {
  id: string; personnel: Person; issued_at: string; issued_by: string; authority_ref: string; issue_condition: string; issue_note: string;
  returned_at: string | null; returned_by: string; outcome: string; return_condition: string; return_note: string;
}
interface Weapon {
  id: string; serial: string; category: Named; org_unit: UnitB; issued_to_unit: UnitB | null; status: string; weapon_type: string;
  make_model: string; caliber: string; condition: string; version: number; custody: Custody | null;
  custody_history?: Custody[]; events?: { kind: string; note: string; actor: string; at: string; to_status: string }[];
}
interface Summary { total: number; in_custody: number; held_by_non_serving: number; by_type: Record<string, number>; by_status: Record<string, number> }

const CONDITIONS = ["serviceable", "needs_repair", "unserviceable"];
const tone = (c: string) => (c === "serviceable" ? "approved" : c === "unserviceable" ? "bad" : "draft");

/** Auditable weapon register: unique serial numbers, who holds each weapon, issue and return, condition and history. */
export function Weapons() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const canManage = can("weapons.manage");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [inCustody, setInCustody] = useState(false);
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  const summary = useFetch<Summary>("/weapons/summary/");
  const list = useFetch<Page<Weapon>>("/weapons/", { q, status, in_custody: inCustody ? 1 : undefined, page });
  const reloadAll = () => { list.reload(); summary.reload(); };

  return (
    <>
      <h1>{t("weap.title")}</h1>
      <ErrorNotice error={summary.error ?? list.error} />
      {summary.data && (
        <section className="card">
          <div className="stat"><span>{t("weap.total")}</span><b>{summary.data.total}</b></div>
          <div className="stat"><span>{t("weap.inCustody")}</span><b>{summary.data.in_custody}</b></div>
          {summary.data.held_by_non_serving > 0 && <Notice kind="error">{t("weap.nonServing", { n: summary.data.held_by_non_serving })}</Notice>}
          {Object.entries(summary.data.by_type).map(([k, n]) => <div className="stat" key={k}><span>{k}</span><b>{n}</b></div>)}
        </section>
      )}
      <section className="card">
        <input type="search" value={q} maxLength={60} placeholder={t("weap.search")} aria-label={t("weap.search")} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <div className="grid">
          <select value={status} aria-label={t("pers.status")} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">{t("common.all")}</option>
            {["in_stock", "issued", "maintenance", "missing", "lost", "retired"].map((s) => <option key={s} value={s}>{t(`astatus.${s}` as Key)}</option>)}
          </select>
          <label className="row"><input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={inCustody} onChange={(e) => { setInCustody(e.target.checked); setPage(1); }} /><span>{t("weap.onlyInCustody")}</span></label>
        </div>
        {canManage && !registering && <div className="row"><button type="button" className="secondary" onClick={() => setRegistering(true)}>{t("weap.register")}</button></div>}
      </section>
      {registering && <RegisterForm onDone={() => { setRegistering(false); reloadAll(); }} onCancel={() => setRegistering(false)} />}
      <ul className="list">
        {(list.data?.results ?? []).map((w) => (
          <li key={w.id} className="item">
            <button type="button" className="secondary" onClick={() => setOpenId(openId === w.id ? null : w.id)}>
              <b>{w.serial}</b> · {w.weapon_type}{w.make_model ? ` · ${w.make_model}` : ""}
            </button>
            <div className="row">
              <Chip tone={w.status === "in_stock" ? "approved" : "draft"}>{t(`astatus.${w.status}` as Key)}</Chip>
              <Chip tone={tone(w.condition)}>{t(`wcond.${w.condition}` as Key)}</Chip>
              <span className="muted">{name(w.issued_to_unit ?? w.org_unit)}</span>
            </div>
            {w.custody && <p className="muted">{t("weap.heldBy")}: {w.custody.personnel.rank.code} {w.custody.personnel.full_name} ({w.custody.personnel.service_number ?? "—"})</p>}
            {openId === w.id && <Detail id={w.id} canManage={canManage} onChanged={reloadAll} />}
          </li>
        ))}
      </ul>
      {list.data && (list.data.next || list.data.previous) && (
        <div className="row">
          <button type="button" className="secondary" disabled={!list.data.previous} onClick={() => setPage(page - 1)}>{t("common.previous")}</button>
          <button type="button" className="secondary" disabled={!list.data.next} onClick={() => setPage(page + 1)}>{t("common.next")}</button>
        </div>
      )}
    </>
  );
}

function RegisterForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { t, name, lang } = useI18n();
  const cats = useFetch<{ results: (Named & { id: string })[] }>("/weapons/categories/");
  const [f, setF] = useState({ category: "", org_unit: "", serial: "", weapon_type: "", make_model: "", caliber: "", condition: "serviceable" });
  const [error, setError] = useState<unknown>(null);
  const catList = cats.data?.results ?? [];
  useEffect(() => { if (catList.length === 1 && !f.category) setF((x) => ({ ...x, category: catList[0].id })); }, [catList.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    try { await api("/weapons/", { method: "POST", body: f }); onDone(); } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <ErrorNotice error={error ?? cats.error} />
      <Field label={t("weap.category")}>
        <select value={f.category} required disabled={catList.length === 0} onChange={set("category")}>
          <option value="">—</option>
          {catList.map((c) => <option key={c.id} value={c.id}>{name(c)}</option>)}
        </select>
      </Field>
      {cats.data && catList.length === 0 && (
        <Notice kind="error">
          {lang === "so"
            ? "Weli ma jirto qayb hub ah oo la ansixiyay. Fur Logistics → Categories, oo ka dhig \"Weapons\" mid la ansixiyay (waxaa sameyn kara isticmaale leh ogolaansho ansixinta qalabka xaddidan), ka dibna halkan dib u soo laadi."
            : "No approved weapon category exists yet. Open Logistics → Categories and approve the \"Weapons\" category (this needs a user with the restricted-approval permission), then reload this page."}
        </Notice>
      )}
      <UnitPicker label={t("weap.holdingUnit")} value={f.org_unit} required onChange={(id) => setF({ ...f, org_unit: id })} params={{ placeable: 1 }} />
      <Field label={t("weap.serial")}><input value={f.serial} required maxLength={64} autoCapitalize="characters" onChange={set("serial")} /></Field>
      <Field label={t("weap.type")}><input value={f.weapon_type} required maxLength={60} onChange={set("weapon_type")} /></Field>
      <Field label={t("weap.makeModel")}><input value={f.make_model} maxLength={120} onChange={set("make_model")} /></Field>
      <Field label={t("weap.caliber")}><input value={f.caliber} maxLength={40} onChange={set("caliber")} /></Field>
      <Field label={t("weap.condition")}>
        <select value={f.condition} onChange={set("condition")}>{CONDITIONS.map((c) => <option key={c} value={c}>{t(`wcond.${c}` as Key)}</option>)}</select>
      </Field>
      <div className="row"><button type="submit">{t("weap.register")}</button><button type="button" className="secondary" onClick={onCancel}>{t("common.cancel")}</button></div>
    </form>
  );
}

function Detail({ id, canManage, onChanged }: { id: string; canManage: boolean; onChanged: () => void }) {
  const { t, name } = useI18n();
  const w = useFetch<Weapon>(`/weapons/${id}/`);
  const [mode, setMode] = useState<"issue" | "return" | "condition" | null>(null);
  const [q, setQ] = useState("");
  const [person, setPerson] = useState("");
  const [condition, setCondition] = useState("serviceable");
  const [authority, setAuthority] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const unit = w.data ? (w.data.issued_to_unit ?? w.data.org_unit) : null;
  const people = useFetch<{ results: Person[] }>(mode === "issue" && unit ? "/weapons/people/" : null, { org_unit: unit?.id, q });
  if (!w.data) return <><ErrorNotice error={w.error} /></>;
  const d = w.data;

  async function run(path: string, body: Record<string, unknown>) {
    setBusy(true); setError(null);
    try { await api(`/weapons/${id}/${path}/`, { method: "POST", body }); setMode(null); setPerson(""); setAuthority(""); setNote(""); w.reload(); onChanged(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (mode === "issue") void run("issue", { personnel: person, condition, authority_ref: authority, note, version: d.version });
    else if (mode === "return") void run("return", { condition, note, version: d.version });
    else void run("condition", { condition, note });
  };
  return (
    <div className="card">
      <ErrorNotice error={error} />
      <div className="stat"><span>{t("weap.serial")}</span><b>{d.serial}</b></div>
      <div className="stat"><span>{t("weap.caliber")}</span><b>{d.caliber || "—"}</b></div>
      <div className="stat"><span>{t("weap.holdingUnit")}</span><b>{name(d.org_unit)}</b></div>
      {canManage && mode === null && (
        <div className="row">
          {!d.custody && ["in_stock", "issued"].includes(d.status) && <button type="button" onClick={() => { setMode("issue"); setCondition(d.condition); }}>{t("weap.issue")}</button>}
          {d.custody && <button type="button" onClick={() => { setMode("return"); setCondition(d.condition); }}>{t("weap.return")}</button>}
          <button type="button" className="secondary" onClick={() => { setMode("condition"); setCondition(d.condition); }}>{t("weap.updateCondition")}</button>
        </div>
      )}
      {mode && (
        <form onSubmit={submit}>
          {mode === "issue" && (
            <>
              <input type="search" value={q} maxLength={60} placeholder={t("weap.findPerson")} aria-label={t("weap.findPerson")} onChange={(e) => setQ(e.target.value)} />
              <Field label={t("weap.holder")}>
                <select value={person} required onChange={(e) => setPerson(e.target.value)}>
                  <option value="">—</option>
                  {(people.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.rank.code} {p.full_name} ({p.service_number ?? "—"})</option>)}
                </select>
              </Field>
              <Field label={t("weap.authority")}><input value={authority} required maxLength={150} onChange={(e) => setAuthority(e.target.value)} /></Field>
            </>
          )}
          <Field label={t("weap.condition")}>
            <select value={condition} onChange={(e) => setCondition(e.target.value)}>{CONDITIONS.map((c) => <option key={c} value={c}>{t(`wcond.${c}` as Key)}</option>)}</select>
          </Field>
          <Field label={t("att.note")}><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
          <div className="row">
            <button type="submit" disabled={busy || (mode === "issue" && !person)}>{t(mode === "issue" ? "weap.issue" : mode === "return" ? "weap.return" : "weap.updateCondition")}</button>
            <button type="button" className="secondary" onClick={() => setMode(null)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
      <h3>{t("weap.history")}</h3>
      {(d.custody_history ?? []).length === 0 && <p className="muted">{t("weap.noHistory")}</p>}
      <ul className="list">
        {(d.custody_history ?? []).map((c) => (
          <li key={c.id} className="item">
            <b>{c.personnel.rank.code} {c.personnel.full_name}</b> ({c.personnel.service_number ?? "—"})
            <p className="muted">{c.issued_at.slice(0, 10)} → {c.returned_at ? c.returned_at.slice(0, 10) : t("weap.stillHeld")} · {c.authority_ref} · {c.issued_by}</p>
            {c.outcome && <Chip tone={c.outcome === "returned" ? "approved" : "bad"}>{t(`weap.outcome.${c.outcome}` as Key)}</Chip>}
          </li>
        ))}
      </ul>
    </div>
  );
}
