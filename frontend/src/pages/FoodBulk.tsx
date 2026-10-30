import { useState, type FormEvent } from "react";
import { api, ApiError, upload } from "../api/client";
import type { FoodOptions } from "../api/types";
import { useFetch } from "../api/useFetch";
import { UnitPicker } from "../components/UnitPicker";
import { ErrorNotice, Field, Loading, Notice } from "../components/ui";
import { useI18n } from "../i18n";
import { downloadText, toCsv } from "../lib/csv";

const B = "/logistics";
const MAX_LINES = 100;

interface ProblemRow { row: number; errors: string[] }

/** Per-row problems the server sends with a 409 (bulk_has_errors / import_has_errors). */
function rowsOf(err: unknown): ProblemRow[] {
  return err instanceof ApiError ? (err.body as unknown as { rows?: ProblemRow[] }).rows ?? [] : [];
}

function useProblemText() {
  const { tr } = useI18n();
  return (code: string) => tr(`err.${code}`) ?? code;
}

// ------------------------------------------------------------------ bulk transfer
interface Line { key: number; unit: string; quantity: string; note: string }
const EMPTY_HEAD = { order_ref: "", issuing_officer: "", order_date: "", issue_note_prefix: "" };

/** One Army order, one source store, many destination units: every line is issued or none is. */
export function BulkTransfer() {
  const { t } = useI18n();
  const problemText = useProblemText();
  const opts = useFetch<FoodOptions>(`${B}/food/options/`);  // fetched here so the balances are current whenever the tab opens
  const [store, setStore] = useState("");
  const [head, setHead] = useState(EMPTY_HEAD);
  const [lines, setLines] = useState<Line[]>([{ key: 1, unit: "", quantity: "", note: "" }]);
  const [nextKey, setNextKey] = useState(2);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<{ n: number; qty: number } | null>(null);
  const [busy, setBusy] = useState(false);

  if (!opts.data) return opts.loading ? <Loading /> : <ErrorNotice error={opts.error} />;
  const stores = opts.data.stores;
  const current = stores.find((s) => s.id === store) ?? stores[0];
  const total = lines.reduce((n, l) => n + (Number(l.quantity) || 0), 0);
  const problems = new Map(rowsOf(error).map((p) => [p.row, p.errors]));
  const setField = (k: keyof typeof EMPTY_HEAD) => (e: { target: { value: string } }) => setHead((h) => ({ ...h, [k]: e.target.value }));
  const change = (key: number, patch: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  function add() {
    setLines((ls) => [...ls, { key: nextKey, unit: "", quantity: "", note: "" }]);
    setNextKey(nextKey + 1);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!current) return;
    setBusy(true); setError(null); setDone(null);
    try {
      const r = await api<{ count: number; quantity: number }>(`${B}/food/allocations/bulk/`, {
        method: "POST",
        body: { stock_line: current.id, ...head,
                lines: lines.map((l) => ({ to_unit: l.unit, quantity: Number(l.quantity), issue_note_ref: l.note })) },
      });
      setDone({ n: r.count, qty: r.quantity });
      setHead(EMPTY_HEAD); setLines([{ key: nextKey, unit: "", quantity: "", note: "" }]); setNextKey(nextKey + 1);
      opts.reload();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h2>{t("fd.bulkTitle")}</h2>
      <p className="muted">{t("fd.bulkIntro")}</p>
      <ErrorNotice error={error} />
      {done && <Notice>{t("fd.bulkDone", { n: done.n, qty: done.qty })}</Notice>}
      <Field label={t("fd.fromStore")}>
        <select value={current?.id ?? ""} onChange={(e) => setStore(e.target.value)} required>
          {stores.map((s) => <option key={s.id} value={s.id}>{s.org_unit_name} · {s.category_name} · {s.quantity} {s.uom}</option>)}
        </select>
      </Field>
      <div className="grid">
        <Field label={t("cr.orderRef")}><input value={head.order_ref} maxLength={150} onChange={setField("order_ref")} required /></Field>
        <Field label={t("cr.issuingOfficer")}><input value={head.issuing_officer} maxLength={150} onChange={setField("issuing_officer")} required /></Field>
        <Field label={t("cr.orderDate")}><input type="date" value={head.order_date} onChange={setField("order_date")} required /></Field>
        <Field label={t("fd.issueNotePrefix")}><input value={head.issue_note_prefix} maxLength={50} onChange={setField("issue_note_prefix")} /></Field>
      </div>
      <p className="muted">{t("fd.issueNotePrefixHelp")}</p>
      {lines.map((l, i) => (
        <div className="item" key={l.key}>
          <b>{t("imp.row", { row: i + 1 })}</b>
          <UnitPicker label={t("fd.toUnit")} value={l.unit} onChange={(id) => change(l.key, { unit: id })} exclude={current?.org_unit} required />
          <div className="grid">
            <Field label={t("fd.quantity")}>
              <input type="number" min={1} step={1} value={l.quantity} onChange={(e) => change(l.key, { quantity: e.target.value })} required />
            </Field>
            <Field label={t("fd.issueNote")}>
              <input value={l.note} maxLength={60} onChange={(e) => change(l.key, { note: e.target.value })} />
            </Field>
          </div>
          {(problems.get(i + 1) ?? []).length > 0 && (
            <Notice kind="error">{(problems.get(i + 1) ?? []).map(problemText).join(" ")}</Notice>
          )}
          {lines.length > 1 && (
            <button type="button" className="secondary" onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}>{t("fd.removeLine")}</button>
          )}
        </div>
      ))}
      <p><b>{t("fd.lineTotal", { total, available: current?.quantity ?? 0, uom: current?.uom ?? "" })}</b></p>
      <div className="row">
        <button type="button" className="secondary" onClick={add} disabled={lines.length >= MAX_LINES}>{t("fd.addLine")}</button>
        <button disabled={busy || !current}>{t("fd.bulkIssue")}</button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------ opening stock from a spreadsheet
interface OpeningPreview {
  total: number; valid: number; can_commit: boolean; rows: ProblemRow[];
  stores: { unit_code: string; unit_name: string; category: string; uom: string; quantity: number; batches: number; earliest_expiry: string | null }[];
}
const COLUMNS = ["unit_code", "category_code", "quantity", "uom", "expires_on", "received_on", "batch_ref", "supplier", "delivery_note_ref", "reorder_level"];

/** Opening food stock from a CSV or Excel file: check first (nothing is saved), then confirm. */
export function OpeningImport() {
  const { t } = useI18n();
  const problemText = useProblemText();
  const [file, setFile] = useState<File | null>(null);
  const [authority, setAuthority] = useState("");
  const [preview, setPreview] = useState<OpeningPreview | null>(null);
  const [saved, setSaved] = useState<{ stores: number; quantity: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const path = `${B}/food/receipts/opening-import/`;

  function choose(f: File | null) { setFile(f); setPreview(null); setError(null); }

  async function check(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setError(null); setPreview(null);
    try { setPreview(await upload<OpeningPreview>(path, "file", file, { authority_ref: authority })); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }

  async function commit() {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const r = await upload<{ stores: number; quantity: number }>(path, "file", file, { authority_ref: authority, confirm: "true" });
      setSaved({ stores: r.stores, quantity: r.quantity });
      setPreview(null); setFile(null); setAuthority("");
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  const fromError = rowsOf(error);
  const problems = fromError.length > 0 ? fromError : preview?.rows ?? [];

  function template() {
    downloadText("food-opening-stock-template.csv", toCsv([COLUMNS, ["UNIT-CODE", "food_rations", "100", "kg", "2027-06-30", "", "BATCH-1", "", "", "50"]]));
  }
  function problemList() {
    downloadText("food-opening-stock-problems.csv", toCsv([
      [t("imp.rowCol"), t("imp.reportCol")],
      ...problems.map((p) => [String(p.row), p.errors.map(problemText).join(" ")]),
    ]));
  }

  if (saved) {
    return (
      <section className="card">
        <Notice>{t("fd.openDone", { stores: saved.stores, qty: saved.quantity })}</Notice>
        <button className="secondary" onClick={() => setSaved(null)}>{t("fd.openAnother")}</button>
      </section>
    );
  }
  return (
    <>
      <form className="card" onSubmit={(e) => void check(e)}>
        <h2>{t("fd.openTitle")}</h2>
        <p>{t("fd.openIntro")}</p>
        <p className="muted">{t("fd.openColumns")}</p>
        <ErrorNotice error={error} />
        <Field label={t("fd.openAuthority")}>
          <input value={authority} maxLength={150} onChange={(e) => { setAuthority(e.target.value); setPreview(null); }} required />
        </Field>
        <Field label={t("fd.openFile")}>
          <input type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                 onChange={(e) => choose(e.target.files?.[0] ?? null)} required />
        </Field>
        <div className="row">
          <button disabled={busy || !file}>{t("fd.openCheck")}</button>
          <button type="button" className="secondary" onClick={template}>{t("fd.openTemplate")}</button>
        </div>
      </form>
      {(preview || problems.length > 0) && (
        <section className="card">
          {preview && <p><b>{t("fd.openSummary", { valid: preview.valid, total: preview.total })}</b></p>}
          {problems.length > 0 && <Notice kind="error">{t("fd.openFix")}</Notice>}
          {preview?.can_commit && <Notice>{t("fd.openReady")}</Notice>}
          <ul className="list">
            {problems.map((p) => (
              <li key={p.row} className="item">
                <b>{t("imp.row", { row: p.row })}</b>
                <div className="muted">{p.errors.map(problemText).join(" ")}</div>
              </li>
            ))}
          </ul>
          {preview?.can_commit && (
            <>
              <h2>{t("fd.openStores")}</h2>
              <ul className="list">
                {preview.stores.map((s) => (
                  <li key={`${s.unit_code}|${s.category}`} className="item">
                    {t("fd.openStoreLine", { unit: s.unit_name, category: s.category, qty: s.quantity, uom: s.uom, batches: s.batches })}
                    {s.earliest_expiry && <span className="muted"> · {t("fd.earliest")} {s.earliest_expiry}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="row">
            {preview?.can_commit && <button onClick={() => void commit()} disabled={busy}>{t("fd.openConfirm")}</button>}
            {problems.length > 0 && <button className="secondary" onClick={problemList}>{t("imp.errorReport")}</button>}
          </div>
        </section>
      )}
    </>
  );
}
