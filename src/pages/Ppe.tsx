import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice, PageHeader, Tabs } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { FilterBar } from "../components/FilterBar";
import { useI18n, type Key } from "../i18n";

interface Named { code: string; name_en: string; name_so: string }
interface UnitB extends Named { id: string }
interface LineRow { id: string; category: Named & { id: string }; org_unit: UnitB; uom: string; in_store: number; held: number; reorder_level: number; below_reorder: boolean }
interface Person { id: string; full_name: string; service_number: string | null; rank: Named }
interface Move {
  id: string; kind: string; quantity: number; size: string; serial: string; condition: string; reference: string; authority_ref: string; note: string; actor: string; at: string;
  personnel: { id: string; full_name: string; service_number: string | null }; category: Named;
}

const KINDS = ["issue", "return", "damaged", "lost", "retired"] as const;
const MODES = [...KINDS, "replace", "inspect"] as const;
type Mode = (typeof MODES)[number];
const CONDITIONS = ["new", "good", "fair", "poor", "unserviceable"];
const today = () => new Date().toISOString().slice(0, 10);

/** Protective equipment: unit stock (from the logistics ledger) and what each person holds. Every quantity comes from the server. */
export function Ppe() {
  const { t, name, lang } = useI18n();
  const { can } = useAuth();
  const [tab, setTab] = useState<"stock" | "history">("stock");
  const [q, setQ] = useState("");
  const [low, setLow] = useState(false);
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [selected, setSelected] = useState<LineRow | null>(null);
  const lines = useFetch<Page<LineRow>>(tab === "stock" ? "/ppe/" : null, { q, below_reorder: low ? 1 : undefined, page, page_size: pageSize === 25 ? undefined : pageSize });
  const ledger = useFetch<Page<Move>>(tab === "history" ? "/ppe/ledger/" : null, { q, kind, page, page_size: pageSize === 25 ? undefined : pageSize });
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(1); };
  const resetAll = () => { setQ(""); setLow(false); setKind(""); setPage(1); };
  const fmt = (iso: string) => new Date(iso).toLocaleString(lang === "so" ? "so-SO" : "en-GB");

  const stockCols: Column<LineRow>[] = [
    { id: "category", header: t("veh.category"), width: 220, locked: true, sort: (r) => name(r.category), cell: (r) => name(r.category) },
    { id: "unit", header: t("veh.unit"), width: 220, sort: (r) => name(r.org_unit), cell: (r) => name(r.org_unit) },
    { id: "store", header: t("ppe.inStore"), width: 120, align: "right", sort: (r) => r.in_store, cell: (r) => <>{r.in_store.toLocaleString()} {r.below_reorder && <Chip tone="bad">{t("log.belowReorder")}</Chip>}</> },
    { id: "held", header: t("ppe.withPersonnel"), width: 150, align: "right", sort: (r) => r.held, cell: (r) => r.held.toLocaleString() },
    { id: "total", header: t("ppe.accountable"), width: 140, align: "right", sort: (r) => r.in_store + r.held, cell: (r) => (r.in_store + r.held).toLocaleString() },
    ...(can("logistics.manage") ? [{ id: "act", header: "", width: 110, locked: true, cell: (r: LineRow) => <button type="button" className="secondary" onClick={() => setSelected(r)}>{t("ppe.manage")}</button> }] : []),
  ];
  const moveCols: Column<Move>[] = [
    { id: "at", header: t("ppe.when"), width: 170, sort: (r) => r.at, cell: (r) => fmt(r.at) },
    { id: "kind", header: t("ppe.kind"), width: 120, sort: (r) => r.kind, cell: (r) => <Chip tone={r.kind === "issue" || r.kind === "return" ? "approved" : "draft"}>{t(`ppe.kind.${r.kind}` as Key)}</Chip> },
    { id: "who", header: t("ppe.holder"), width: 230, sort: (r) => r.personnel.full_name, cell: (r) => `${r.personnel.full_name} (${r.personnel.service_number ?? "—"})` },
    { id: "cat", header: t("veh.category"), width: 190, sort: (r) => name(r.category), cell: (r) => name(r.category) },
    { id: "qty", header: t("ppe.qty"), width: 80, align: "right", sort: (r) => r.quantity, cell: (r) => r.quantity },
    { id: "ref", header: t("ppe.reference"), width: 130, sort: (r) => r.reference, cell: (r) => r.reference || "—" },
    { id: "cond", header: t("veh.condition"), width: 130, hidden: true, sort: (r) => r.condition, cell: (r) => t(`cond.${r.condition}` as Key) },
    { id: "size", header: t("ppe.size"), width: 80, hidden: true, cell: (r) => r.size || "—" },
    { id: "serial", header: t("ppe.serial"), width: 140, hidden: true, cell: (r) => r.serial || "—" },
    { id: "note", header: t("ppe.note"), width: 240, hidden: true, cell: (r) => r.note || "—" },
    { id: "actor", header: t("ppe.by"), width: 130, hidden: true, sort: (r) => r.actor, cell: (r) => r.actor },
  ];
  const filtered = !!(q || low || kind);
  return (
    <>
      <PageHeader title={t("ppe.title")} subtitle={t("ppe.subtitle")} />
      <Tabs tabs={[{ id: "stock", label: t("ppe.tab.stock") }, { id: "history", label: t("ppe.tab.history") }]} value={tab} onChange={(v) => { setTab(v); resetAll(); }} />
      <ErrorNotice error={lines.error ?? ledger.error} />
      {tab === "stock" ? (
        <>
          <FilterBar search={{ value: q, label: t("ppe.search"), onChange: reset(setQ) }} filters={[]}
                     advancedExtra={<label className="check"><input type="checkbox" checked={low} onChange={(e) => reset(setLow)(e.target.checked)} /><span>{t("ppe.onlyLow")}</span></label>}
                     custom={[{ id: "low", label: t("ppe.onlyLow"), active: low, onClear: () => reset(setLow)(false) }]} onReset={resetAll} />
          {selected && <LineActions line={lines.data?.results.find((r) => r.id === selected.id) ?? selected} onClose={() => setSelected(null)} onDone={() => { lines.reload(); }} />}
          <DataTable id="ppe-stock" caption={t("ppe.tab.stock")} columns={stockCols} rows={lines.data?.results} rowKey={(r) => r.id} loading={lines.loading}
                     filtered={filtered} onReset={resetAll} empty={{ icon: "lock", title: t("ppe.none") }}
                     page={page} count={lines.data?.count} pageSize={pageSize} onPage={setPage} onPageSize={(n) => { setPageSize(n); setPage(1); }} />
        </>
      ) : (
        <>
          <FilterBar search={{ value: q, label: t("ppe.searchHistory"), onChange: reset(setQ) }}
                     filters={[{ id: "kind", label: t("ppe.kind"), value: kind, onChange: reset(setKind), options: KINDS.map((k) => ({ value: k, label: t(`ppe.kind.${k}` as Key) })) }]}
                     custom={[]} onReset={resetAll} />
          <DataTable id="ppe-ledger" caption={t("ppe.tab.history")} columns={moveCols} rows={ledger.data?.results} rowKey={(r) => r.id} loading={ledger.loading}
                     filtered={filtered} onReset={resetAll} empty={{ icon: "lock", title: t("ppe.noneHistory") }}
                     page={page} count={ledger.data?.count} pageSize={pageSize} onPage={setPage} onPageSize={(n) => { setPageSize(n); setPage(1); }} />
        </>
      )}
    </>
  );
}

function LineActions({ line, onClose, onDone }: { line: LineRow; onClose: () => void; onDone: () => void }) {
  const { t, name } = useI18n();
  const [mode, setMode] = useState<Mode>("issue");
  const [pq, setPq] = useState("");
  const [person, setPerson] = useState("");
  const [f, setF] = useState({ quantity: "1", size: "", serial: "", condition: "new", reference: "", authority_ref: "", note: "", next_due: "" });
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const people = useFetch<{ results: Person[] }>("/ppe/people/", { org_unit: line.org_unit.id, q: pq });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const needsRef = mode === "issue" || mode === "return" || mode === "replace";
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null); setDone(false);
    try {
      const base = `/ppe/${line.id}`;
      if (mode === "inspect") {
        await api(`${base}/inspect/`, { method: "POST", body: { personnel: person, condition: f.condition, inspected_on: today(), next_due: f.next_due || null, note: f.note } });
      } else if (mode === "replace") {
        await api(`${base}/replace/`, { method: "POST", body: { personnel: person, quantity: Number(f.quantity), out_kind: "damaged", size: f.size, serial: f.serial, condition: f.condition, reference: f.reference, authority_ref: f.authority_ref, note: f.note } });
      } else {
        await api(`${base}/movement/`, { method: "POST", body: { personnel: person, kind: mode, quantity: Number(f.quantity), size: f.size, serial: f.serial, condition: f.condition, reference: f.reference, authority_ref: f.authority_ref, note: f.note } });
      }
      setDone(true); onDone();
      setF((x) => ({ ...x, reference: "", note: "", authority_ref: "", serial: "" }));
    } catch (err) { setError(err); } finally { setBusy(false); }
  };
  return (
    <section className="card">
      <h3>{name(line.category)} · {name(line.org_unit)}</h3>
      <p className="muted">{t("ppe.inStore")}: <b>{line.in_store.toLocaleString()}</b> · {t("ppe.withPersonnel")}: <b>{line.held.toLocaleString()}</b></p>
      <form onSubmit={submit}>
        <Field label={t("ppe.action")}>
          <select value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
            {MODES.map((m) => <option key={m} value={m}>{t(`ppe.mode.${m}` as Key)}</option>)}
          </select>
        </Field>
        <input type="search" value={pq} maxLength={60} placeholder={t("weap.findPerson")} aria-label={t("weap.findPerson")} onChange={(e) => setPq(e.target.value)} />
        <Field label={t("ppe.holder")}>
          <select value={person} required onChange={(e) => setPerson(e.target.value)}>
            <option value="">—</option>
            {(people.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.rank.code} {p.full_name} ({p.service_number ?? "—"})</option>)}
          </select>
        </Field>
        {mode !== "inspect" && <Field label={t("ppe.qty")}><input type="number" min={1} max={1000000} step={1} value={f.quantity} required onChange={set("quantity")} /></Field>}
        <Field label={t("veh.condition")}>
          <select value={f.condition} onChange={set("condition")}>{CONDITIONS.map((c) => <option key={c} value={c}>{t(`cond.${c}` as Key)}</option>)}</select>
        </Field>
        {(mode === "issue" || mode === "replace") && <>
          <Field label={t("ppe.size")}><input value={f.size} maxLength={20} onChange={set("size")} /></Field>
          <Field label={t("ppe.serial")}><input value={f.serial} maxLength={64} onChange={set("serial")} /></Field>
        </>}
        {needsRef && <Field label={t("ppe.reference")}><input value={f.reference} required maxLength={60} onChange={set("reference")} /></Field>}
        {(mode === "lost" || mode === "replace") && <Field label={t("weap.authority")}><input value={f.authority_ref} required={mode === "lost"} maxLength={150} onChange={set("authority_ref")} /></Field>}
        {mode === "inspect" && <Field label={t("ppe.nextDue")}><input type="date" value={f.next_due} min={today()} onChange={set("next_due")} /></Field>}
        {mode !== "issue" && mode !== "return" && <Field label={t("ppe.note")}><input value={f.note} required={mode !== "inspect" || f.condition === "unserviceable"} maxLength={300} onChange={set("note")} /></Field>}
        <ErrorNotice error={error} />
        {done && <Notice>{t("ppe.saved")}</Notice>}
        <div className="row"><button type="submit" disabled={busy}>{t("common.save")}</button><button type="button" className="secondary" onClick={onClose}>{t("common.back")}</button></div>
      </form>
    </section>
  );
}
