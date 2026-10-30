import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { FoodAllocationOut, FoodBatchOut, FoodOptions, FoodSupplier, FoodWarnings } from "../api/types";
import { useFetch } from "../api/useFetch";
import { UnitPicker } from "../components/UnitPicker";
import { BulkTransfer, OpeningImport } from "./FoodBulk";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice, Tabs } from "../components/ui";
import { useI18n, type Key } from "../i18n";

const B = "/logistics";
type Tab = "warnings" | "receipts" | "allocations" | "bulk" | "opening" | "suppliers";

function useForm<T extends Record<string, string>>(initial: T) {
  const [v, setV] = useState<T>(initial);
  return { v, set: (k: keyof T) => (e: { target: { value: string } }) => setV((cur) => ({ ...cur, [k]: e.target.value })), reset: () => setV(initial) };
}

function Warnings() {
  const { t } = useI18n();
  const w = useFetch<FoodWarnings>(`${B}/food/warnings/`);
  if (w.loading) return <Loading />;
  if (w.error || !w.data) return <ErrorNotice error={w.error} />;
  const d = w.data;
  return (
    <>
      <div className="card"><h2>{t("fd.lowStock")}</h2>
        {d.low_stock.length === 0 ? <p className="muted">{t("fd.none")}</p> : d.low_stock.map((x) => (
          <p key={x.stock_line}>{x.org_unit} · {x.category}: <strong>{x.quantity}</strong> {x.uom} ({t("fd.reorder")} {x.reorder_level})</p>))}
      </div>
      <div className="card"><h2>{t("fd.expiring", { days: d.days })}</h2>
        {d.expiring.length === 0 ? <p className="muted">{t("fd.none")}</p> : d.expiring.map((x) => (
          <p key={x.batch}>{x.expired && <Chip tone="rejected">{t("fd.expired")}</Chip>} {x.org_unit} · {x.category} · {x.remaining} {x.uom} · {x.expires_on}{x.supplier ? ` · ${x.supplier}` : ""}</p>))}
      </div>
      <div className="card"><h2>{t("fd.unbatched")}</h2>
        {d.unbatched.length === 0 ? <p className="muted">{t("fd.none")}</p> : d.unbatched.map((x) => (
          <p key={x.stock_line}>{x.org_unit} · {x.category}: {t("fd.ledger")} {x.ledger} / {t("fd.batched")} {x.batched}</p>))}
      </div>
    </>
  );
}

function Receipts({ options }: { options: FoodOptions }) {
  const { t, name } = useI18n();
  const list = useFetch<{ results: FoodBatchOut[] }>(`${B}/food/receipts/`);
  const suppliers = useFetch<{ results: FoodSupplier[] }>(`${B}/suppliers/`, { active: "true" });
  const f = useForm({ category: options.categories[0]?.id ?? "", supplier: "", quantity: "", uom: "kg", expires_on: "", batch_ref: "", delivery_note_ref: "", order_ref: "" });
  const [unit, setUnit] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null); setDone(false);
    try {
      await api(`${B}/food/receipts/`, { method: "POST", body: { ...f.v, org_unit: unit, quantity: Number(f.v.quantity), expires_on: f.v.expires_on || null } });
      setDone(true); f.reset(); list.reload();
    } catch (err) { setError(err); }
  }
  return (
    <>
      <form className="card" onSubmit={(e) => void submit(e)}>
        <h2>{t("fd.newReceipt")}</h2>
        <ErrorNotice error={error} />
        {done && <Notice>{t("fd.saved")}</Notice>}
        <UnitPicker label={t("fd.store")} value={unit} onChange={setUnit} required />
        <Field label={t("fd.category")}>
          <select value={f.v.category} onChange={f.set("category")} required>{options.categories.map((c) => <option key={c.id} value={c.id}>{name(c)}</option>)}</select>
        </Field>
        <Field label={t("fd.supplier")}>
          <select value={f.v.supplier} onChange={f.set("supplier")} required><option value="" />{(suppliers.data?.results ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        </Field>
        <div className="grid">
          <Field label={t("fd.quantity")}><input type="number" min={1} value={f.v.quantity} onChange={f.set("quantity")} required /></Field>
          <Field label={t("fd.uom")}><input value={f.v.uom} maxLength={16} onChange={f.set("uom")} /></Field>
          <Field label={t("fd.expiresOn")}><input type="date" value={f.v.expires_on} onChange={f.set("expires_on")} /></Field>
          <Field label={t("fd.batchRef")}><input value={f.v.batch_ref} maxLength={60} onChange={f.set("batch_ref")} /></Field>
          <Field label={t("fd.deliveryNote")}><input value={f.v.delivery_note_ref} maxLength={60} onChange={f.set("delivery_note_ref")} required /></Field>
          <Field label={t("cr.orderRef")}><input value={f.v.order_ref} maxLength={150} onChange={f.set("order_ref")} required /></Field>
        </div>
        <button>{t("common.create")}</button>
      </form>
      {list.loading ? <Loading /> : <ErrorNotice error={list.error} />}
      {(list.data?.results ?? []).map((b) => (
        <div className="card" key={b.id}>
          <strong>{b.org_unit_name} · {b.category}</strong>: {b.quantity} {b.uom} ({t("fd.remaining")} {b.remaining})
          <p className="muted">{b.supplier} · {b.received_on}{b.expires_on ? ` · ${t("fd.expiresOn")} ${b.expires_on}` : ""} · {b.delivery_note_ref} · {b.order_ref}</p>
        </div>
      ))}
    </>
  );
}

function Allocations({ options }: { options: FoodOptions }) {
  const { t, lang } = useI18n();
  const list = useFetch<{ results: FoodAllocationOut[] }>(`${B}/food/allocations/`);
  const f = useForm({ stock_line: options.stores[0]?.id ?? "", quantity: "", order_ref: "", issuing_officer: "", order_date: "", issue_note_ref: "" });
  const [to, setTo] = useState("");
  const [error, setError] = useState<unknown>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    try { await api(`${B}/food/allocations/`, { method: "POST", body: { ...f.v, to_unit: to, quantity: Number(f.v.quantity) } }); f.reset(); list.reload(); }
    catch (err) { setError(err); }
  }
  return (
    <>
      <form className="card" onSubmit={(e) => void submit(e)}>
        <h2>{t("fd.newAllocation")}</h2>
        <ErrorNotice error={error} />
        <Field label={t("fd.fromStore")}>
          <select value={f.v.stock_line} onChange={f.set("stock_line")} required>
            {options.stores.map((s) => <option key={s.id} value={s.id}>{s.org_unit_name} · {s.category_name} · {s.quantity} {s.uom}</option>)}
          </select>
        </Field>
        <UnitPicker label={t("fd.toUnit")} value={to} onChange={setTo} required />
        <div className="grid">
          <Field label={t("fd.quantity")}><input type="number" min={1} value={f.v.quantity} onChange={f.set("quantity")} required /></Field>
          <Field label={t("fd.issueNote")}><input value={f.v.issue_note_ref} maxLength={60} onChange={f.set("issue_note_ref")} required /></Field>
          <Field label={t("cr.orderRef")}><input value={f.v.order_ref} maxLength={150} onChange={f.set("order_ref")} required /></Field>
          <Field label={t("cr.issuingOfficer")}><input value={f.v.issuing_officer} maxLength={150} onChange={f.set("issuing_officer")} required /></Field>
          <Field label={t("cr.orderDate")}><input type="date" value={f.v.order_date} onChange={f.set("order_date")} required /></Field>
        </div>
        <button>{t("fd.issue")}</button>
      </form>
      {list.loading ? <Loading /> : <ErrorNotice error={list.error} />}
      {(list.data?.results ?? []).map((a) => <AllocationRow key={a.id} a={a} lang={lang} onChanged={list.reload} />)}
    </>
  );
}

function AllocationRow({ a, lang, onChanged }: { a: FoodAllocationOut; lang: string; onChanged: () => void }) {
  const { t } = useI18n();
  const f = useForm({ received_by_name: "", receipt_note_ref: "", reason: "" });
  const [error, setError] = useState<unknown>(null);
  async function act(name: "acknowledge" | "cancel") {
    setError(null);
    try { await api(`${B}/food/allocations/${a.id}/${name}/`, { method: "POST", body: { version: a.version, ...f.v } }); onChanged(); }
    catch (err) { setError(err); }
  }
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{a.from_unit_name} → {a.to_unit_name}: {a.quantity} {a.uom} {a.category}</strong>
        <Chip tone={a.status === "cancelled" ? "rejected" : a.status === "delivered" ? "approved" : "pending"}>{t(`fd.status.${a.status}` as Key)}</Chip>
      </div>
      <p className="muted">{t("cr.order")}: {a.order_ref} · {a.issuing_officer} · {a.order_date} · {t("fd.issueNote")} {a.issue_note_ref} · {a.issued_by} · {formatDate(a.issued_at, lang)}
        {a.delivered_at && <><br />{t("fd.receivedBy")}: {a.received_by_name} · {a.receipt_note_ref} · {formatDate(a.delivered_at, lang)}</>}
        {a.cancel_reason && <><br />{a.cancel_reason}</>}</p>
      <ErrorNotice error={error} />
      {a.status === "issued" && (
        <div className="grid">
          <Field label={t("fd.receivedBy")}><input value={f.v.received_by_name} maxLength={150} onChange={f.set("received_by_name")} /></Field>
          <Field label={t("fd.receiptNote")}><input value={f.v.receipt_note_ref} maxLength={60} onChange={f.set("receipt_note_ref")} /></Field>
          <Field label={t("cr.reason")}><input value={f.v.reason} maxLength={300} onChange={f.set("reason")} /></Field>
          <div className="row"><button onClick={() => void act("acknowledge")}>{t("fd.recordDelivery")}</button>
            <button className="secondary" onClick={() => void act("cancel")}>{t("fd.cancel")}</button></div>
        </div>
      )}
    </div>
  );
}

function Suppliers() {
  const { t } = useI18n();
  const list = useFetch<{ results: FoodSupplier[] }>(`${B}/suppliers/`);
  const f = useForm({ name: "", phone: "", address: "", notes: "" });
  const [error, setError] = useState<unknown>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null);
    try { await api(`${B}/suppliers/`, { method: "POST", body: f.v }); f.reset(); list.reload(); } catch (err) { setError(err); }
  }
  async function toggle(s: FoodSupplier) {
    setError(null);
    try { await api(`${B}/suppliers/${s.id}/`, { method: "PATCH", body: { active: !s.active, version: s.version } }); list.reload(); } catch (err) { setError(err); }
  }
  return (
    <>
      <form className="card" onSubmit={(e) => void submit(e)}>
        <h2>{t("fd.newSupplier")}</h2>
        <ErrorNotice error={error} />
        <div className="grid">
          <Field label={t("fd.supplierName")}><input value={f.v.name} maxLength={150} onChange={f.set("name")} required /></Field>
          <Field label={t("fd.phone")}><input value={f.v.phone} maxLength={30} onChange={f.set("phone")} /></Field>
          <Field label={t("fd.address")}><input value={f.v.address} maxLength={200} onChange={f.set("address")} /></Field>
          <Field label={t("fd.notes")}><input value={f.v.notes} maxLength={300} onChange={f.set("notes")} /></Field>
        </div>
        <button>{t("common.create")}</button>
      </form>
      {list.loading ? <Loading /> : <ErrorNotice error={list.error} />}
      {(list.data?.results ?? []).map((s) => (
        <div className="card row" key={s.id} style={{ justifyContent: "space-between" }}>
          <span><strong>{s.name}</strong> <span className="muted">{s.phone} {s.address}</span></span>
          <button className="secondary" onClick={() => void toggle(s)}>{s.active ? t("common.active") : t("common.inactive")}</button>
        </div>
      ))}
    </>
  );
}

export function FoodStores() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("warnings");
  const options = useFetch<FoodOptions>(`${B}/food/options/`);
  return (
    <main>
      <h1>{t("fd.title")}</h1>
      <p className="muted">{t("fd.intro")}</p>
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "warnings", label: t("fd.tab.warnings") }, { id: "receipts", label: t("fd.tab.receipts") },
        { id: "allocations", label: t("fd.tab.allocations") }, { id: "bulk", label: t("fd.tab.bulk") },
        { id: "opening", label: t("fd.tab.opening") }, { id: "suppliers", label: t("fd.tab.suppliers") }]} />
      {options.loading ? <Loading /> : options.error || !options.data ? <ErrorNotice error={options.error} /> : (
        <>
          {tab === "warnings" && <Warnings />}
          {tab === "receipts" && <Receipts options={options.data} />}
          {tab === "allocations" && <Allocations options={options.data} />}
          {tab === "bulk" && <BulkTransfer />}
          {tab === "opening" && <OpeningImport />}
          {tab === "suppliers" && <Suppliers />}
        </>
      )}
    </main>
  );
}
