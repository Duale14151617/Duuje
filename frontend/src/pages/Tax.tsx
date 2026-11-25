import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, PageHeader } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { UnitPicker } from "../components/UnitPicker";
import { ExportPdfButton, type PdfContent } from "../components/ExportPdfButton";
import { downloadText, toCsv } from "../lib/csv";
import { useI18n } from "../i18n";
import { formatMoney, formatMoneyList } from "../lib/format";

interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface TaxType { id: string; code: string; name_en: string; name_so: string; kind: string; default_amount: string | null; currency: string; recurring: boolean; period_months: number; active: boolean; version: number }
interface Cover { tax_type: string; paid_until: string | null; overdue: boolean }
interface Veh { id: string; plate: string; owner_name: string; owner_phone: string; vehicle_kind: string; make_model: string; org_unit: UnitB | null; cover?: Cover[]; version: number }
interface Pay {
  id: string; receipt_no: string; vehicle: { id: string; plate: string; owner_name: string }; tax_type: { code: string; name_en: string; name_so: string };
  amount: string; currency: string; paid_on: string; period_to: string | null; reference: string; handover: string | null; void: boolean; version: number;
}
interface Ho { id: string; number: string; org_unit: UnitB | null; currency: string; expected_amount: string; payments_count: number; handed_by: string; handed_at: string; status: "submitted" | "confirmed"; counted_amount: string | null; difference: string | null; version: number }
interface Summary { today: Tot[]; this_month: Tot[]; uncollected: Tot[]; waiting_to_count: number }
interface Tot { currency: string; total: string; count: number }
interface NameB { code: string; name_en: string; name_so: string }
interface Report {
  from: string; to: string; voided: number;
  rows: { date: string; unit: NameB; tax_type: NameB; currency: string; count: number; total: string }[];
  held_by_collectors: { unit: NameB; currency: string; count: number; total: string }[];
}
interface Overdue { types: NameB[]; truncated: boolean; results: (Veh & { paid_until: Record<string, string | null> })[] }
const today = () => new Date().toISOString().slice(0, 10);

const tot = (a: Tot[]) => formatMoneyList(a);
const clean = (f: Record<string, FormDataEntryValue>) => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== ""));

export function Tax() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const canRecord = can("tax.record"), canConfirm = can("tax.confirm"), canConfigure = can("tax.configure");
  const [tab, setTab] = useState<"vehicles" | "receipts" | "handovers" | "report" | "types">("vehicles");
  const [q, setQ] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [adding, setAdding] = useState(false);
  const [unit, setUnit] = useState("");
  const [hoUnit, setHoUnit] = useState("");
  const [paying, setPaying] = useState<Veh | null>(null);
  const [error, setError] = useState<unknown>(null);
  const types = useFetch<{ results: TaxType[] }>("/tax/types/", canConfigure ? { all: 1 } : undefined);
  const vehicles = useFetch<Page<Veh>>(tab === "vehicles" ? "/tax/vehicles/" : null, { q: q.trim() || undefined, overdue: overdue ? 1 : undefined, page_size: 50 });
  const pays = useFetch<Page<Pay>>(tab === "receipts" ? "/tax/payments/" : null, { q: q.trim() || undefined, include_void: 1, page_size: 100 });
  const hos = useFetch<Page<Ho>>(tab === "handovers" ? "/tax/handovers/" : null, { page_size: 50 });
  const summary = useFetch<Summary>("/tax/summary/");
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [repUnit, setRepUnit] = useState("");
  const report = useFetch<Report>(tab === "report" ? "/tax/report/" : null, { from, to, unit: repUnit || undefined });
  const reload = () => { vehicles.reload(); pays.reload(); hos.reload(); summary.reload(); types.reload(); };
  const typeList = types.data?.results ?? [];
  const typeName = (c: string) => { const x = typeList.find((y) => y.code === c); return x ? name(x) : c; };

  async function post(path: string, body: Record<string, unknown>): Promise<boolean> {
    setError(null);
    try { await api(path, { method: "POST", body }); reload(); return true; } catch (e) { setError(e); return false; }
  }

  const vehCols: Column<Veh>[] = [
    { id: "plate", header: t("tax.plate"), cell: (x) => x.plate, sort: (x) => x.plate },
    { id: "owner", header: t("tax.owner"), cell: (x) => `${x.owner_name}${x.owner_phone ? ` · ${x.owner_phone}` : ""}` },
    { id: "kind", header: t("tax.kind"), cell: (x) => [x.vehicle_kind, x.make_model].filter(Boolean).join(" · ") || "—" },
    { id: "cover", header: t("tax.cover"), cell: (x) => (x.cover ?? []).map((c) => (
      <span key={c.tax_type}>{typeName(c.tax_type)}: {c.paid_until ?? t("tax.never")} <Chip tone={c.overdue ? "bad" : "approved"}>{c.overdue ? t("tax.overdue") : t("tax.ok")}</Chip>{" "}</span>)) },
    { id: "act", header: "", cell: (x) => canRecord ? <button type="button" className="secondary" onClick={() => setPaying(paying?.id === x.id ? null : x)}>{t("tax.receive")}</button> : null },
  ];
  const payCols: Column<Pay>[] = [
    { id: "no", header: t("tax.receiptNo"), cell: (x) => x.receipt_no, sort: (x) => x.receipt_no },
    { id: "date", header: t("tax.paidOn"), cell: (x) => x.paid_on, sort: (x) => x.paid_on },
    { id: "plate", header: t("tax.plate"), cell: (x) => x.vehicle.plate },
    { id: "type", header: t("tax.type"), cell: (x) => name(x.tax_type) },
    { id: "amount", header: t("tax.amount"), align: "right", cell: (x) => formatMoney(x.amount, x.currency), sort: (x) => Number(x.amount) },
    { id: "until", header: t("tax.paidUntil"), cell: (x) => x.period_to ?? x.reference ?? "—" },
    { id: "ho", header: t("tax.handover"), cell: (x) => (x.void ? <Chip tone="bad">{t("tax.void")}</Chip> : x.handover ?? <Chip tone="draft">{t("tax.withCollector")}</Chip>) },
    { id: "print", header: "", cell: (x) => x.void ? null : <ExportPdfButton build={() => receiptPdf(x)} filename={`receipt-${x.receipt_no}`} /> },
    { id: "act", header: "", cell: (x) => canRecord && !x.void && !x.handover ? <button type="button" className="secondary" onClick={() => { const reason = window.prompt(t("tax.voidReason")); if (reason) void post(`/tax/${x.id}/payments/void/`, { version: x.version, reason }); }}>{t("tax.voidBtn")}</button> : null },
  ];
  const hoCols: Column<Ho>[] = [
    { id: "no", header: t("tax.handoverNo"), cell: (x) => x.number },
    { id: "unit", header: t("tax.station"), cell: (x) => (x.org_unit ? name(x.org_unit) : "—") },
    { id: "by", header: t("tax.handedBy"), cell: (x) => `${x.handed_by} · ${x.handed_at.slice(0, 10)}` },
    { id: "exp", header: t("tax.expected"), align: "right", cell: (x) => `${formatMoney(x.expected_amount, x.currency)} (${x.payments_count})` },
    { id: "cnt", header: t("tax.counted"), align: "right", cell: (x) => (x.counted_amount ? formatMoney(x.counted_amount, x.currency) : "—") },
    { id: "diff", header: t("tax.difference"), align: "right", cell: (x) => (x.difference === null ? "—" : <Chip tone={Number(x.difference) === 0 ? "approved" : "bad"}>{x.difference}</Chip>) },
    { id: "act", header: "", cell: (x) => canConfirm && x.status === "submitted" ? <button type="button" onClick={() => {
      const counted = window.prompt(t("tax.countedPrompt", { expected: x.expected_amount, currency: x.currency })); if (counted === null || counted === "") return;
      const note = Number(counted) !== Number(x.expected_amount) ? window.prompt(t("tax.differencePrompt")) ?? "" : "";
      void post(`/tax/${x.id}/handovers/confirm/`, { version: x.version, counted_amount: counted, note });
    }}>{t("tax.count")}</button> : x.status === "submitted" ? <Chip tone="draft">{t("tax.waiting")}</Chip> : <Chip tone="approved">{t("tax.confirmed")}</Chip> },
  ];

  async function addVehicle(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    if (await post("/tax/vehicles/create/", { ...clean(Object.fromEntries(new FormData(form).entries())), org_unit: unit })) { setAdding(false); form.reset(); }
  }
  async function receive(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!paying) return;
    const form = e.currentTarget;
    if (await post("/tax/payments/create/", { ...clean(Object.fromEntries(new FormData(form).entries())), vehicle: paying.id })) { setPaying(null); form.reset(); }
  }

  // A reprint of the receipt on record. The paper receipt given to the payer stays the original.
  const receiptPdf = (x: Pay): PdfContent => ({
    title: `${t("tax.receiptTitle")} ${x.receipt_no}`, subtitle: t("tax.reprintNote"),
    sections: [{ columns: [{ header: t("tax.field"), width: 1 }, { header: t("tax.value"), width: 2 }], rows: [
      [t("tax.receiptNo"), x.receipt_no], [t("tax.plate"), x.vehicle.plate], [t("tax.owner"), x.vehicle.owner_name], [t("tax.type"), name(x.tax_type)],
      [t("tax.amount"), formatMoney(x.amount, x.currency)], [t("tax.paidOn"), x.paid_on], ...(x.period_to ? [[t("tax.paidUntil"), x.period_to]] : []),
      ...(x.reference ? [[t("tax.reference"), x.reference]] : [])] }],
  });
  const stamp = (d: string | null | undefined) => d ?? t("tax.never");
  async function overdueRows() {
    const r = await api<Overdue>("/tax/overdue-export/");
    const head = [t("tax.plate"), t("tax.owner"), t("tax.phone"), t("tax.kind"), t("tax.station"), ...r.types.map((x) => `${name(x)}: ${t("tax.cover")}`)];
    const body = r.results.map((v) => [v.plate, v.owner_name, v.owner_phone, [v.vehicle_kind, v.make_model].filter(Boolean).join(" "), v.org_unit ? name(v.org_unit) : "", ...r.types.map((x) => stamp(v.paid_until[x.code]))]);
    return { head, body, truncated: r.truncated };
  }
  async function overdueCsv() {
    setError(null);
    try { const o = await overdueRows(); downloadText(`overdue-vehicles-${today()}.csv`, toCsv([o.head, ...o.body])); } catch (e) { setError(e); }
  }
  const overduePdf = async (): Promise<PdfContent> => {
    const o = await overdueRows();
    return { title: t("tax.overdueTitle"), subtitle: o.truncated ? t("tax.truncated") : undefined, landscape: true,
      sections: [{ columns: o.head.map((h, i) => ({ header: h, width: i < 2 ? 2 : 1 })), rows: o.body }] };
  };
  const repRows = () => (report.data?.rows ?? []).map((r) => [r.date, name(r.unit), name(r.tax_type), String(r.count), formatMoney(r.total, r.currency)]);
  const repHead = () => [t("tax.paidOn"), t("tax.station"), t("tax.type"), t("tax.receipts"), t("tax.amount")];
  const reportPdf = (): PdfContent => ({
    title: t("tax.reportTitle"), subtitle: `${from} → ${to} · ${t("tax.voidedCount", { n: report.data?.voided ?? 0 })}`,
    sections: [
      { columns: repHead().map((h, i) => ({ header: h, width: i === 1 ? 2 : 1, align: i >= 3 ? "right" as const : "left" as const })), rows: repRows() },
      ...(report.data?.held_by_collectors.length ? [{ heading: t("tax.heldHeading"), columns: [{ header: t("tax.station"), width: 2 }, { header: t("tax.receipts"), width: 1, align: "right" as const }, { header: t("tax.amount"), width: 1, align: "right" as const }],
        rows: report.data.held_by_collectors.map((h) => [name(h.unit), String(h.count), formatMoney(h.total, h.currency)]) }] : []),
    ],
  });

  const s = summary.data;
  return (
    <>
      <PageHeader title={t("tax.title")} subtitle={t("tax.subtitle")}
        actions={canRecord && tab === "vehicles" ? <button type="button" onClick={() => setAdding(!adding)}>{t("tax.addVehicle")}</button> : undefined} />
      {s && <p>{t("tax.summary", { today: tot(s.today), month: tot(s.this_month), cash: tot(s.uncollected), waiting: s.waiting_to_count })}</p>}
      <div className="row">
        {(["vehicles", "receipts", "handovers", "report", ...(canConfigure ? ["types"] : [])] as const).map((k) => (
          <button key={k} type="button" className={tab === k ? "" : "secondary"} onClick={() => { setTab(k as typeof tab); setAdding(false); setPaying(null); }}>{t(`tax.tab.${k}` as never)}</button>))}
        {(tab === "vehicles" || tab === "receipts") && <Field label={t("common.search")}><input type="search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={60} /></Field>}
        {tab === "vehicles" && <label className="field"><span>{t("tax.overdueOnly")}</span><input type="checkbox" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} /></label>}
      </div>
      {error != null && <ErrorNotice error={error} />}
      {adding && (
        <form onSubmit={(e) => void addVehicle(e)} className="card">
          <UnitPicker label={t("tax.station")} value={unit} onChange={setUnit} required />
          <Field label={t("tax.plate")}><input name="plate" required maxLength={20} /></Field>
          <Field label={t("tax.owner")}><input name="owner_name" required maxLength={200} /></Field>
          <Field label={t("tax.phone")}><input name="owner_phone" maxLength={40} inputMode="tel" /></Field>
          <Field label={t("tax.idRef")}><input name="id_ref" maxLength={80} /></Field>
          <Field label={t("tax.kind")}><input name="vehicle_kind" maxLength={60} /></Field>
          <Field label={t("tax.makeModel")}><input name="make_model" maxLength={120} /></Field>
          <button type="submit">{t("tax.save")}</button>
        </form>
      )}
      {paying && (
        <form onSubmit={(e) => void receive(e)} className="card">
          <h2>{paying.plate} · {paying.owner_name}</h2>
          <Field label={t("tax.type")}><select name="tax_type" required defaultValue="">
            <option value="" disabled>—</option>{typeList.filter((x) => x.active).map((x) => <option key={x.id} value={x.id}>{name(x)}{x.default_amount ? ` — ${formatMoney(x.default_amount, x.currency)}` : ""}</option>)}</select></Field>
          <Field label={t("tax.receiptNo")}><input name="receipt_no" required maxLength={40} /></Field>
          <Field label={t("tax.amountOnReceipt")}><input name="amount" type="number" step="0.01" min="0.01" inputMode="decimal" /></Field>
          <Field label={t("tax.paidOn")}><input name="paid_on" type="date" max={new Date().toISOString().slice(0, 10)} /></Field>
          <Field label={t("tax.reference")}><input name="reference" maxLength={150} /></Field>
          <button type="submit">{t("tax.record")}</button>
        </form>
      )}
      {tab === "vehicles" && (
        <p>
          <button type="button" className="secondary" onClick={() => void overdueCsv()}>{t("tax.overdueCsv")}</button>{" "}
          <ExportPdfButton build={overduePdf} filename="overdue-vehicles" onError={setError} />
        </p>)}
      {tab === "vehicles" && <DataTable id="tax-vehicles" caption={t("tax.tab.vehicles")} columns={vehCols} rows={vehicles.data?.results ?? []} rowKey={(x) => x.id} loading={vehicles.loading} empty={{ title: t("tax.empty") }} />}
      {tab === "receipts" && <DataTable id="tax-receipts" caption={t("tax.tab.receipts")} columns={payCols} rows={pays.data?.results ?? []} rowKey={(x) => x.id} loading={pays.loading} empty={{ title: t("tax.empty") }} />}
      {tab === "handovers" && (<>
        {canRecord && (
          <form className="card" onSubmit={(e) => { e.preventDefault(); void post("/tax/handovers/create/", { org_unit: hoUnit }); }}>
            <p className="muted">{t("tax.handoverHelp")}</p>
            <UnitPicker label={t("tax.station")} value={hoUnit} onChange={setHoUnit} required />
            <button type="submit">{t("tax.handOver")}</button>
          </form>)}
        <DataTable id="tax-handovers" caption={t("tax.tab.handovers")} columns={hoCols} rows={hos.data?.results ?? []} rowKey={(x) => x.id} loading={hos.loading} empty={{ title: t("tax.empty") }} />
      </>)}
      {tab === "report" && (
        <section>
          <div className="row">
            <Field label={t("tax.from")}><input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label={t("tax.to")}><input type="date" value={to} min={from} max={today()} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
          <UnitPicker label={t("tax.station")} value={repUnit} onChange={setRepUnit} allowAll />
          <p>
            <button type="button" className="secondary" disabled={!report.data} onClick={() => downloadText(`tax-collections-${from}-${to}.csv`, toCsv([repHead(), ...repRows()]))}>{t("tax.reportCsv")}</button>{" "}
            <ExportPdfButton build={reportPdf} filename="tax-collections" disabled={!report.data} onError={setError} />
          </p>
          {report.data && <p>{t("tax.voidedCount", { n: report.data.voided })}</p>}
          <table>
            <thead><tr>{repHead().map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>
              {repRows().map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} style={j >= 3 ? { textAlign: "right" } : undefined}>{c}</td>)}</tr>)}
              {repRows().length === 0 && <tr><td colSpan={5}>{t("tax.empty")}</td></tr>}
            </tbody>
          </table>
          {(report.data?.held_by_collectors.length ?? 0) > 0 && (<>
            <h3>{t("tax.heldHeading")}</h3>
            <ul>{report.data?.held_by_collectors.map((h, i) => <li key={i}>{name(h.unit)} · {h.count} · {formatMoney(h.total, h.currency)}</li>)}</ul>
          </>)}
        </section>
      )}
      {tab === "types" && canConfigure && (
        <section className="card">
          <p className="muted">{t("tax.typesHelp")}</p>
          <ul>{typeList.map((x) => (
            <li key={x.id}>{name(x)} · {x.recurring ? t("tax.recurring", { months: x.period_months }) : t("tax.oneOff")} · {x.default_amount ? formatMoney(x.default_amount, x.currency) : t("tax.noAmount")}{" "}
              <button type="button" className="secondary" onClick={() => { const v = window.prompt(t("tax.amountPrompt", { name: name(x) }), x.default_amount ?? ""); if (v !== null) void post(`/tax/${x.id}/types/update/`, { version: x.version, default_amount: v }); }}>{t("tax.setAmount")}</button>{" "}
              <button type="button" className="secondary" onClick={() => void post(`/tax/${x.id}/types/update/`, { version: x.version, active: !x.active })}>{x.active ? t("tax.switchOff") : t("tax.switchOn")}</button></li>))}
          </ul>
        </section>
      )}
    </>
  );
}
