import { useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, uploadForm } from "../api/client";
import type { Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar } from "../components/FilterBar";
import { Icon } from "../components/Icon";
import { useI18n, type Key } from "../i18n";

interface Named { code: string; name_en: string; name_so: string }
interface Classification extends Named { id: string }
export interface CatalogueItem {
  id: string; code: string; name: string; kind: "vehicle_model" | "mounted_weapon"; classification: Classification | null;
  manufacturer: string; description: string; source_ref: string; verification: "unverified" | "verified" | "needs_review";
  verification_note: string; verified_by: string | null; verified_at: string | null; active: boolean; photo_id: string | null; version: number;
}
interface Spec { name: string; value: string; unit: string }
interface PhotoT { id: string; caption: string; uploaded_at: string }
interface Detail extends CatalogueItem {
  specs: Spec[]; photos: PhotoT[]; vehicles_in_scope: number | null; created_by: string;
  capabilities: { manage: boolean; verify: boolean };
}

const tone = (v: string) => (v === "verified" ? "approved" : v === "needs_review" ? "bad" : "draft");
const VERIFICATION = ["unverified", "verified", "needs_review"] as const;

export function VerificationChip({ v }: { v: string }) {
  const { t } = useI18n();
  return <Chip tone={tone(v)}>{t(`eq.ver.${v}` as Key)}</Chip>;
}

/** Equipment Reference Catalogue. Reference data only; every figure and label comes from the server. */
export function Equipment() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const kind = sp.get("kind") ?? "";
  const classification = sp.get("classification") ?? "";
  const verification = sp.get("verification") ?? "";
  const inactive = sp.get("include_inactive") === "1";
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const setParam = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n); setPage(1); };
  const vcats = useFetch<{ results: Classification[] }>("/vehicles/categories/");
  const wcats = useFetch<{ results: Classification[] }>("/equipment/weapon-categories/");
  const list = useFetch<Page<CatalogueItem>>("/equipment/", { q, kind: kind || undefined, classification: classification || undefined, verification: verification || undefined, include_inactive: inactive ? 1 : undefined, page });
  const manage = can("equipment.manage");
  const options = [...(kind !== "mounted_weapon" ? vcats.data?.results ?? [] : []), ...(kind !== "vehicle_model" ? wcats.data?.results ?? [] : [])];
  const filtered = !!(q || kind || classification || verification || inactive);
  const resetAll = () => { setQ(""); setSp({}); setPage(1); };

  const columns: Column<CatalogueItem>[] = [
    { id: "name", header: t("eq.name"), width: 210, locked: true, sort: (i) => i.name, cell: (i) => <Link to={`/equipment/${i.code}`}>{i.name}</Link> },
    { id: "kind", header: t("eq.kind"), width: 150, sort: (i) => i.kind, cell: (i) => t(`eq.kind.${i.kind}` as Key) },
    { id: "class", header: t("eq.classification"), width: 210, sort: (i) => (i.classification ? name(i.classification) : ""), cell: (i) => (i.classification ? name(i.classification) : "—") },
    { id: "maker", header: t("eq.manufacturer"), width: 200, sort: (i) => i.manufacturer, cell: (i) => i.manufacturer || "—" },
    { id: "ver", header: t("eq.verification"), width: 150, sort: (i) => i.verification, cell: (i) => <><VerificationChip v={i.verification} />{!i.active && <> <Chip>{t("eq.inactive")}</Chip></>}</> },
    { id: "photo", header: t("eq.photos"), width: 110, cell: (i) => (i.photo_id ? <img alt={i.name} src={`/api/v1/equipment/${i.id}/photos/${i.photo_id}/image/`} style={{ height: 36, borderRadius: 4 }} loading="lazy" /> : <span className="muted">—</span>) },
  ];

  return (
    <>
      <PageHeader title={t("eq.title")} subtitle={t("eq.refOnly")} actions={manage && !adding ? <button type="button" onClick={() => setAdding(true)}><Icon name="plus" size={16} /><span>{t("eq.add")}</span></button> : undefined} />
      <ErrorNotice error={list.error} />
      <FilterBar
        search={{ value: q, label: t("eq.search"), onChange: (v) => { setQ(v); setPage(1); } }}
        filters={[
          { id: "kind", label: t("eq.kind"), value: kind, onChange: (v) => { const n = new URLSearchParams(sp); n.delete("classification"); if (v) n.set("kind", v); else n.delete("kind"); setSp(n); setPage(1); }, options: ["vehicle_model", "mounted_weapon"].map((k) => ({ value: k, label: t(`eq.kind.${k}` as Key) })) },
          { id: "classification", label: t("eq.classification"), value: classification, onChange: (v) => setParam("classification", v), options: options.map((c) => ({ value: c.code, label: name(c) })) },
          { id: "verification", label: t("eq.verification"), value: verification, onChange: (v) => setParam("verification", v), options: VERIFICATION.map((v) => ({ value: v, label: t(`eq.ver.${v}` as Key) })) },
        ]}
        advancedExtra={manage ? <label className="check"><input type="checkbox" checked={inactive} onChange={(e) => setParam("include_inactive", e.target.checked ? "1" : "")} /><span>{t("eq.showInactive")}</span></label> : undefined}
        custom={[{ id: "inactive", label: t("eq.showInactive"), active: inactive, onClear: () => setParam("include_inactive", "") }]}
        onReset={resetAll} />
      {adding && <CreateForm vcats={vcats.data?.results ?? []} wcats={wcats.data?.results ?? []} onDone={() => { setAdding(false); list.reload(); }} onCancel={() => setAdding(false)} />}
      {manage && <WeaponCategoryManager cats={wcats.data?.results ?? []} onDone={wcats.reload} />}
      <DataTable id="equipment" caption={t("eq.title")} columns={columns} rows={list.data?.results} rowKey={(i) => i.id} loading={list.loading}
                 filtered={filtered} onReset={resetAll} empty={{ icon: "box", title: t("eq.none") }} page={page} count={list.data?.count} pageSize={25} onPage={setPage} onPageSize={() => undefined} />
    </>
  );
}

function CreateForm({ vcats, wcats, onDone, onCancel }: { vcats: Classification[]; wcats: Classification[]; onDone: () => void; onCancel: () => void }) {
  const { t, name } = useI18n();
  const [f, setF] = useState({ kind: "vehicle_model", name: "", classification: "", manufacturer: "", description: "", source_ref: "" });
  const [error, setError] = useState<unknown>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value, ...(k === "kind" ? { classification: "" } : {}) });
  const cats = f.kind === "vehicle_model" ? vcats : wcats;
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    const { classification, ...rest } = f;
    try { await api("/equipment/", { method: "POST", body: { ...rest, [f.kind === "vehicle_model" ? "vehicle_category" : "weapon_category"]: classification } }); onDone(); } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <ErrorNotice error={error} />
      <Field label={t("eq.kind")}><select value={f.kind} onChange={set("kind")}>{["vehicle_model", "mounted_weapon"].map((k) => <option key={k} value={k}>{t(`eq.kind.${k}` as Key)}</option>)}</select></Field>
      <Field label={t("eq.name")}><input value={f.name} required maxLength={120} onChange={set("name")} /></Field>
      <Field label={t("eq.classification")}><select value={f.classification} required onChange={set("classification")}><option value="" />{cats.map((c) => <option key={c.id} value={c.code}>{name(c)}</option>)}</select></Field>
      <Field label={t("eq.manufacturer")}><input value={f.manufacturer} maxLength={120} onChange={set("manufacturer")} /></Field>
      <Field label={t("eq.description")}><input value={f.description} maxLength={1000} onChange={set("description")} /></Field>
      <Field label={t("eq.source")}><input value={f.source_ref} maxLength={300} onChange={set("source_ref")} /></Field>
      <div className="row"><button type="submit">{t("eq.create")}</button><button type="button" className="secondary" onClick={onCancel}>{t("common.cancel")}</button></div>
    </form>
  );
}

function WeaponCategoryManager({ cats, onDone }: { cats: Classification[]; onDone: () => void }) {
  const { t, name } = useI18n();
  const [f, setF] = useState({ code: "", name_en: "", name_so: "" });
  const [error, setError] = useState<unknown>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    try { await api("/equipment/weapon-categories/", { method: "POST", body: f }); setF({ code: "", name_en: "", name_so: "" }); onDone(); } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>{t("eq.weaponCategories")}</h3>
      <ErrorNotice error={error} />
      <ul className="list">{cats.map((c) => <li key={c.id} className="item">{name(c)} <span className="muted">({c.code})</span></li>)}</ul>
      <Field label={t("veh.categoryCode")}><input value={f.code} required maxLength={40} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
      <Field label={t("veh.categoryName")}><input value={f.name_en} required maxLength={120} onChange={(e) => setF({ ...f, name_en: e.target.value })} /></Field>
      <Field label={t("veh.categoryNameSo")}><input value={f.name_so} maxLength={120} onChange={(e) => setF({ ...f, name_so: e.target.value })} /></Field>
      <div className="row"><button type="submit">{t("eq.newWeaponCategory")}</button></div>
    </form>
  );
}

export function SpecTable({ rows }: { rows: Spec[] }) {
  return (
    <section className="card">
      {rows.map((s) => <div className="stat" key={`${s.name}-${s.value}`}><span>{s.name}</span><b>{s.value}{s.unit ? ` ${s.unit}` : ""}</b></div>)}
    </section>
  );
}

/** Editable list of specification lines, saved as one audited replacement. Used for catalogue entries and for single vehicles. */
export function SpecEditor({ initial, saveLabel, onSave }: { initial: Spec[]; saveLabel: string; onSave: (rows: Spec[]) => Promise<void> }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<Spec[]>(initial);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (i: number, k: keyof Spec, v: string) => setRows(rows.map((r, n) => (n === i ? { ...r, [k]: v } : r)));
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await onSave(rows.filter((r) => r.name.trim() || r.value.trim())); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <ErrorNotice error={error} />
      {rows.map((r, i) => (
        <div className="row" key={i}>
          <input value={r.name} placeholder={t("eq.specName")} aria-label={t("eq.specName")} maxLength={60} onChange={(e) => set(i, "name", e.target.value)} />
          <input value={r.value} placeholder={t("eq.specValue")} aria-label={t("eq.specValue")} maxLength={200} onChange={(e) => set(i, "value", e.target.value)} />
          <input value={r.unit} placeholder={t("eq.specUnit")} aria-label={t("eq.specUnit")} maxLength={20} style={{ maxWidth: 90 }} onChange={(e) => set(i, "unit", e.target.value)} />
          <button type="button" className="secondary" onClick={() => setRows(rows.filter((_, n) => n !== i))} aria-label={t("veh.removeArmament")}>×</button>
        </div>
      ))}
      <div className="row">
        <button type="button" className="secondary" onClick={() => setRows([...rows, { name: "", value: "", unit: "" }])}>{t("eq.addSpec")}</button>
        <button type="submit" disabled={busy}>{saveLabel}</button>
      </div>
    </form>
  );
}

export function EquipmentDetail() {
  const { t, name } = useI18n();
  const { id = "" } = useParams();
  const d = useFetch<Detail>(`/equipment/${id}/`);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [f, setF] = useState({ name: "", manufacturer: "", description: "", source_ref: "" });
  const [caption, setCaption] = useState("");
  const [file, setFile] = useState<File | null>(null);
  if (!d.data) return <>{d.error ? <ErrorNotice error={d.error} /> : <Loading />}</>;
  const x = d.data;
  const post = async (path: string, body: Record<string, unknown>) => { await api(`/equipment/${x.id}/${path}/`, { method: "POST", body: { version: x.version, ...body } }); d.reload(); };
  const run = async (fn: () => Promise<void>) => { setBusy(true); setError(null); try { await fn(); } catch (err) { setError(err); } finally { setBusy(false); } };
  async function addPhoto(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const form = new FormData(); form.append("file", file); form.append("caption", caption);
    await run(async () => { await uploadForm(`/equipment/${x.id}/photos/upload/`, form); setFile(null); setCaption(""); (e.target as HTMLFormElement).reset(); d.reload(); });
  }
  return (
    <>
      <p><Link to="/equipment">← {t("eq.back")}</Link></p>
      <h1>{x.name}</h1>
      <Notice>{t("eq.refOnly")}</Notice>
      <ErrorNotice error={error} />
      <section className="card">
        <div className="stat"><span>{t("eq.kind")}</span><b>{t(`eq.kind.${x.kind}` as Key)}</b></div>
        <div className="stat"><span>{t("eq.classification")}</span><b>{x.classification ? name(x.classification) : "—"}</b></div>
        <div className="stat"><span>{t("eq.manufacturer")}</span><b>{x.manufacturer || "—"}</b></div>
        <div className="stat"><span>{t("eq.source")}</span><b>{x.source_ref || "—"}</b></div>
        {x.vehicles_in_scope !== null && x.kind === "vehicle_model" && <div className="stat"><span>{t("eq.vehiclesInScope")}</span><b><Link to={`/vehicles?reference_model=${x.code}`}>{x.vehicles_in_scope}</Link></b></div>}
        <div className="row"><VerificationChip v={x.verification} />{!x.active && <Chip>{t("eq.inactive")}</Chip>}{x.verified_by && <span className="muted">{t("eq.verifiedBy")}: {x.verified_by} · {x.verified_at?.slice(0, 10)}</span>}</div>
        {x.verification_note && <p className="muted">{x.verification_note}</p>}
        {x.description && <p>{x.description}</p>}
      </section>
      {x.capabilities.verify && (
        <form className="card" onSubmit={(e) => { e.preventDefault(); }}>
          <h3>{t("eq.verify")}</h3>
          <Field label={t("eq.note")}><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
          <div className="row">
            <button type="button" disabled={busy} onClick={() => void run(() => post("verify", { result: "verified", note }))}>{t("eq.markVerified")}</button>
            <button type="button" className="secondary" disabled={busy || !note.trim()} onClick={() => void run(() => post("verify", { result: "needs_review", note }))}>{t("eq.needsReview")}</button>
          </div>
        </form>
      )}
      {x.capabilities.manage && !editing && (
        <div className="row">
          <button type="button" className="secondary" onClick={() => { setF({ name: x.name, manufacturer: x.manufacturer, description: x.description, source_ref: x.source_ref }); setEditing(true); }}>{t("eq.edit")}</button>
          <button type="button" className="secondary" disabled={busy} onClick={() => void run(() => post("edit", { active: !x.active }))}>{x.active ? t("eq.switchOff") : t("eq.switchOn")}</button>
        </div>
      )}
      {editing && (
        <form className="card" onSubmit={(e) => { e.preventDefault(); void run(async () => { await post("edit", f); setEditing(false); }); }}>
          <Field label={t("eq.name")}><input value={f.name} required maxLength={120} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label={t("eq.manufacturer")}><input value={f.manufacturer} maxLength={120} onChange={(e) => setF({ ...f, manufacturer: e.target.value })} /></Field>
          <Field label={t("eq.description")}><input value={f.description} maxLength={1000} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <Field label={t("eq.source")}><input value={f.source_ref} maxLength={300} onChange={(e) => setF({ ...f, source_ref: e.target.value })} /></Field>
          <div className="row"><button type="submit" disabled={busy}>{t("eq.save")}</button><button type="button" className="secondary" onClick={() => setEditing(false)}>{t("common.cancel")}</button></div>
        </form>
      )}
      <h2>{t("eq.photos")}</h2>
      {x.photos.length === 0 && <p className="muted">{t("eq.noPhotos")}</p>}
      <div className="row" style={{ flexWrap: "wrap", alignItems: "flex-start" }}>
        {x.photos.map((p) => (
          <figure key={p.id} className="flush maxw-240">
            <img alt={p.caption || x.name} src={`/api/v1/equipment/${x.id}/photos/${p.id}/image/`} style={{ width: "100%", borderRadius: 6 }} loading="lazy" />
            <figcaption className="muted">{p.caption}</figcaption>
            {x.capabilities.manage && <button type="button" className="secondary" disabled={busy} onClick={() => { const reason = window.prompt(t("eq.reason")); if (reason) void run(async () => { await api(`/equipment/${x.id}/photos/${p.id}/withdraw/`, { method: "POST", body: { reason } }); d.reload(); }); }}>{t("eq.withdraw")}</button>}
          </figure>
        ))}
      </div>
      {x.capabilities.manage && (
        <form className="card" onSubmit={(e) => void addPhoto(e)}>
          <h3>{t("eq.addPhoto")}</h3>
          <Field label={t("eq.caption")}><input value={caption} maxLength={150} onChange={(e) => setCaption(e.target.value)} /></Field>
          <Field label={t("veh.chooseFile")}><input type="file" required accept="image/jpeg,image/png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
          <div className="row"><button type="submit" disabled={busy || !file}>{t("eq.addPhoto")}</button></div>
        </form>
      )}
      <h2>{t("eq.specs")}</h2>
      {x.capabilities.manage
        ? <SpecEditor key={x.version} initial={x.specs} saveLabel={t("eq.saveSpecs")} onSave={async (rows) => { await post("specs", { specs: rows }); }} />
        : x.specs.length === 0 ? <p className="muted">{t("eq.noSpecs")}</p> : <SpecTable rows={x.specs} />}
    </>
  );
}
