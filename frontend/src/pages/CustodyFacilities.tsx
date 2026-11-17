import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, PageHeader } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n } from "../i18n";

interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface Facility {
  id: string; code: string; kind: "jail_center" | "prison"; name_en: string; name_so: string; org_unit: UnitB | null; location: string;
  capacity: number | null; operated_by: string; active: boolean; version: number; held_now: number | null; received_total: number | null;
  status: "unverified" | "operational" | "suspended" | "closed"; status_note: string; status_by: string; usable: boolean;
  capacity_effective: number | null; cells: number | null; available: number | null; over_capacity: boolean | null;
}
interface Cell { id: string; code: string; name: string; capacity: number; note: string; active: boolean; occupied: number; available: number; version: number }
const clean = (f: Record<string, FormDataEntryValue>) => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== ""));

export function CustodyFacilities() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const canEdit = can("detention.manage");
  const canVerify = can("detention.verify");
  const [statusFor, setStatusFor] = useState<Facility | null>(null);
  const [cellsFor, setCellsFor] = useState<Facility | null>(null);
  const cells = useFetch<{ results: Cell[] }>(cellsFor ? `/custody-facilities/${cellsFor.id}/cells/` : null);
  const [kind, setKind] = useState("");
  const [adding, setAdding] = useState(false);
  const [newKind, setNewKind] = useState<"jail_center" | "prison">("jail_center");
  const [unit, setUnit] = useState("");
  const [error, setError] = useState<unknown>(null);
  const list = useFetch<{ results: Facility[] }>("/custody-facilities/", { kind: kind || undefined });

  async function post(path: string, body: Record<string, unknown>): Promise<boolean> {
    setError(null);
    try { await api(path, { method: "POST", body }); list.reload(); return true; } catch (e) { setError(e); return false; }
  }
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const body = { ...clean(Object.fromEntries(new FormData(form).entries())), kind: newKind, ...(newKind === "jail_center" ? { org_unit: unit } : {}) };
    if (await post("/custody-facilities/", body)) { setAdding(false); form.reset(); }
  }

  const cols: Column<Facility>[] = [
    { id: "name", header: t("fac.nameEn"), cell: (x) => name(x), sort: (x) => x.name_en },
    { id: "code", header: t("fac.code"), cell: (x) => x.code, sort: (x) => x.code },
    { id: "kind", header: t("fac.kind"), cell: (x) => <Chip tone={x.kind === "prison" ? "draft" : "approved"}>{t(`fac.kind.${x.kind}` as never)}</Chip> },
    { id: "unit", header: t("fac.station"), cell: (x) => (x.org_unit ? name(x.org_unit) : "—") },
    { id: "by", header: t("fac.operator"), cell: (x) => x.operated_by || "—" },
    { id: "status", header: t("fac.status"), cell: (x) => (x.kind === "jail_center" || x.status !== "unverified" ? (<>
      <Chip tone={x.status === "operational" ? "approved" : x.status === "unverified" ? "draft" : "bad"}>{t(`fac.status.${x.status}` as never)}</Chip>
      {x.over_capacity && <> <Chip tone="bad">{t("fac.overCapacity")}</Chip></>}</>) : <Chip tone="draft">{t("fac.status.unverified")}</Chip>) },
    { id: "cap", header: t("fac.capacity"), align: "right", cell: (x) => (x.kind === "jail_center" ? `${x.capacity_effective ?? t("fac.capacityUnknown")}${x.available != null ? ` (${x.available} ${t("fac.available")})` : ""}` : (x.capacity ?? "—")) },
    { id: "now", header: `${t("fac.heldNow")} / ${t("fac.received")}`, align: "right", cell: (x) => (x.kind === "jail_center" ? x.held_now ?? 0 : x.received_total ?? 0) },
    { id: "state", header: "", cell: (x) => (
      <>{x.active ? null : <Chip tone="bad">{t("fac.off")}</Chip>}
        {canVerify && <> <button type="button" className="secondary" onClick={() => setStatusFor(statusFor?.id === x.id ? null : x)}>{t("fac.setStatus")}</button></>}
        {x.kind === "jail_center" && <> <button type="button" className="secondary" onClick={() => setCellsFor(cellsFor?.id === x.id ? null : x)}>{t("fac.cellsOpen")}</button></>}
        {canEdit && <> <button type="button" className="secondary" onClick={() => void post(`/custody-facilities/${x.id}/edit/`, { version: x.version, active: !x.active })}>{x.active ? t("fac.switchOff") : t("fac.switchOn")}</button></>}</>) },
  ];

  return (
    <>
      <PageHeader title={t("fac.title")} subtitle={t("fac.subtitle")}
        actions={canEdit ? <button type="button" onClick={() => setAdding(!adding)}>{t("fac.add")}</button> : undefined} />
      <section className="card">
        <h3>{t("fac.explainJailTitle")}</h3>
        <p>{t("fac.explainJail")}</p>
        <p className="muted">{t("fac.verifyHelp")}</p>
        <h3>{t("fac.explainPrisonTitle")}</h3>
        <p>{t("fac.explainPrison")}</p>
      </section>
      <div className="row">
        <Field label={t("fac.kind")}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">{t("fac.all")}</option>
            <option value="jail_center">{t("fac.kind.jail_center")}</option>
            <option value="prison">{t("fac.kind.prison")}</option>
          </select>
        </Field>
      </div>
      {error != null && <ErrorNotice error={error} />}
      {adding && (
        <form onSubmit={(e) => void add(e)} className="card">
          <Field label={t("fac.kind")}>
            <select value={newKind} onChange={(e) => setNewKind(e.target.value as "jail_center" | "prison")}>
              <option value="jail_center">{t("fac.kind.jail_center")}</option><option value="prison">{t("fac.kind.prison")}</option>
            </select>
          </Field>
          {newKind === "jail_center" && <UnitPicker label={t("fac.station")} value={unit} onChange={setUnit} required />}
          <Field label={t("fac.code")}><input name="code" required maxLength={64} /></Field>
          <Field label={t("fac.nameEn")}><input name="name_en" required maxLength={150} /></Field>
          <Field label={t("fac.nameSo")}><input name="name_so" maxLength={150} /></Field>
          <Field label={t("fac.location")}><input name="location" maxLength={200} /></Field>
          <Field label={t("fac.capacity")}><input name="capacity" type="number" min={0} inputMode="numeric" /></Field>
          <Field label={t("fac.operator")}><input name="operated_by" maxLength={150} /></Field>
          <button type="submit">{t("fac.save")}</button>
        </form>
      )}
      {statusFor && (
        <form className="card" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; void post(`/custody-facilities/${statusFor.id}/set_status/`, { version: statusFor.version, ...clean(Object.fromEntries(new FormData(f).entries())) }).then((ok) => { if (ok) setStatusFor(null); }); }}>
          <h3>{name(statusFor)}</h3>
          <Field label={t("fac.status")}><select name="status" defaultValue="operational">{["operational", "suspended", "closed"].map((k) => <option key={k} value={k}>{t(`fac.status.${k}` as never)}</option>)}</select></Field>
          <Field label={t("fac.statusNote")}><input name="note" required maxLength={300} /></Field>
          <button type="submit">{t("fac.save")}</button>
        </form>)}
      {cellsFor && (
        <section className="card" aria-label={t("fac.cells")}>
          <h3>{t("fac.cells")}: {name(cellsFor)}</h3>
          {(cells.data?.results.length ?? 0) === 0 ? <p className="muted">{t("fac.noCells")}</p> : (
            <ul>{cells.data!.results.map((c) => (
              <li key={c.id}><strong>{c.code}</strong>{c.name ? ` · ${c.name}` : ""} · {t("fac.occupied")} {c.occupied}/{c.capacity}{c.note ? ` · ${c.note}` : ""}{c.active ? "" : ` · ${t("fac.off")}`}
                {canEdit && <> <button type="button" className="secondary" onClick={() => void post(`/custody-facilities/${cellsFor.id}/edit_cell/`, { cell: c.id, version: c.version, active: !c.active }).then(() => cells.reload())}>{c.active ? t("fac.switchOff") : t("fac.switchOn")}</button></>}</li>))}</ul>)}
          {canEdit && (
            <form onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; void post(`/custody-facilities/${cellsFor.id}/add_cell/`, clean(Object.fromEntries(new FormData(f).entries()))).then((ok) => { if (ok) { f.reset(); cells.reload(); } }); }}>
              <Field label={t("fac.cellCode")}><input name="code" required maxLength={30} /></Field>
              <Field label={t("fac.cellName")}><input name="name" maxLength={100} /></Field>
              <Field label={t("fac.cellCapacity")}><input name="capacity" type="number" min={1} max={1000} required inputMode="numeric" /></Field>
              <Field label={t("fac.cellNote")}><input name="note" maxLength={200} /></Field>
              <button type="submit">{t("fac.addCell")}</button>
            </form>)}
        </section>)}
      <DataTable id="custody-facilities" caption={t("fac.title")} columns={cols} rows={list.data?.results ?? []} rowKey={(x) => x.id} loading={list.loading} empty={{ title: t("fac.empty") }} />
    </>
  );
}
