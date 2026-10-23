import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n, type Key } from "../i18n";

interface Named { code: string; name_en: string; name_so: string }
interface Line { id: string; category: Named; org_unit: Named; uom: string; quantity: number }
interface Tx { id: string; kind: string; delta: number; balance_after: number; reason: string; external_ref: string; authority_ref: string; actor: string; at: string }
interface Statement {
  balance_start: number; opening_recorded: number; received: number; returned: number; adjusted_up: number; issued: number; expended: number;
  lost_damaged: number; adjusted_down: number; transferred_out: number; closing: number;
  check: { computed_closing: number; matches_balances: boolean; current_quantity: number; matches_current: boolean | null };
  outstanding_discrepancies: number;
  reconciliations: { reconciliation: string; status: string; expected: number | null; counted: number; variance: number; outstanding: boolean }[];
  transactions: Tx[];
}

const KINDS = ["opening", "receive", "issue", "return", "expenditure", "loss", "damage", "adjust"];
const ROWS: [Key, keyof Statement][] = [
  ["ammo.balanceStart", "balance_start"], ["ammo.openingRecorded", "opening_recorded"], ["ammo.received", "received"], ["ammo.returned", "returned"],
  ["ammo.adjustedUp", "adjusted_up"], ["ammo.issued", "issued"], ["ammo.expended", "expended"], ["ammo.lostDamaged", "lost_damaged"],
  ["ammo.adjustedDown", "adjusted_down"], ["ammo.transferredOut", "transferred_out"], ["ammo.closing", "closing"],
];
const today = () => new Date().toISOString().slice(0, 10);

/** Ammunition ledger: balances are calculated from the saved movements. Vouchers stop double entry; adjustments, losses and damage are authorized. */
export function Ammunition() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const [unit, setUnit] = useState("");
  const [lineId, setLineId] = useState<string | null>(null);
  const lines = useFetch<Line[] | { results: Line[] }>("/logistics/ammunition/", { org_unit: unit || undefined });
  const rows = Array.isArray(lines.data) ? lines.data : lines.data?.results ?? [];
  return (
    <>
      <h1>{t("ammo.title")}</h1>
      <section className="card"><UnitPicker label={t("pers.unit")} value={unit} allowAll onChange={(id) => { setUnit(id); setLineId(null); }} params={{ placeable: 1 }} /></section>
      <ErrorNotice error={lines.error} />
      {rows.length === 0 && !lines.loading && <p className="muted">{t("ammo.none")}</p>}
      <ul className="list">
        {rows.map((l) => (
          <li key={l.id} className="item">
            <button type="button" className="secondary" onClick={() => setLineId(lineId === l.id ? null : l.id)}>{name(l.category)} · {name(l.org_unit)}</button>
            <div className="row"><b>{l.quantity}</b><span className="muted">{l.uom}</span></div>
            {lineId === l.id && <LineDetail id={l.id} canPost={can("logistics.manage")} onPosted={lines.reload} />}
          </li>
        ))}
      </ul>
    </>
  );
}

function LineDetail({ id, canPost, onPosted }: { id: string; canPost: boolean; onPosted: () => void }) {
  const { t } = useI18n();
  const [from, setFrom] = useState(today().slice(0, 8) + "01");
  const [to, setTo] = useState(today());
  const st = useFetch<Statement>(`/logistics/ammunition/${id}/statement/`, { from, to });
  const [f, setF] = useState({ kind: "receive", quantity: "", reason: "", external_ref: "", authority_ref: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const needsVoucher = ["receive", "issue", "return"].includes(f.kind);
  const needsAuthority = ["loss", "damage", "adjust"].includes(f.kind);
  const needsReason = ["opening", "expenditure", "loss", "damage", "adjust"].includes(f.kind);

  async function post(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      await api(`/logistics/ammunition/${id}/movement/`, { method: "POST", body: { ...f, quantity: Number(f.quantity) } });
      setF({ ...f, quantity: "", reason: "", external_ref: "", authority_ref: "" }); st.reload(); onPosted();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const d = st.data;
  return (
    <div className="card">
      <ErrorNotice error={st.error} />
      <div className="grid">
        <Field label={t("att.from")}><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label={t("att.to")}><input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      {d && (
        <>
          {!d.check.matches_balances && <Notice kind="error">{t("ammo.mismatch")}</Notice>}
          {d.outstanding_discrepancies > 0 && <Notice kind="error">{t("ammo.outstanding", { n: d.outstanding_discrepancies })}</Notice>}
          {ROWS.map(([label, key]) => <div className="stat" key={key}><span>{t(label)}</span><b>{d[key] as number}</b></div>)}
          {d.reconciliations.length > 0 && (
            <>
              <h3>{t("ammo.reconciliations")}</h3>
              <ul className="list">{d.reconciliations.map((r) => (
                <li key={r.reconciliation} className="item">
                  {t("ammo.expectedCounted", { e: r.expected ?? 0, c: r.counted })} <Chip tone={r.variance === 0 ? "approved" : "bad"}>{r.variance > 0 ? `+${r.variance}` : r.variance}</Chip>
                  {r.outstanding && <Chip tone="bad">{t("ammo.openDiscrepancy")}</Chip>}
                </li>))}
              </ul>
            </>
          )}
        </>
      )}
      {canPost && (
        <form onSubmit={(e) => void post(e)}>
          <h3>{t("ammo.record")}</h3>
          <ErrorNotice error={error} />
          <Field label={t("ammo.kind")}>
            <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{t(`ammo.kind.${k}` as Key)}</option>)}</select>
          </Field>
          <Field label={t("ammo.quantity")}><input type="number" step={1} min={f.kind === "adjust" ? undefined : 1} value={f.quantity} required onChange={(e) => setF({ ...f, quantity: e.target.value })} /></Field>
          {f.kind === "adjust" && <p className="muted">{t("ammo.adjustHint")}</p>}
          {needsVoucher && <Field label={t("ammo.voucher")}><input value={f.external_ref} required maxLength={60} onChange={(e) => setF({ ...f, external_ref: e.target.value })} /></Field>}
          {needsReason && <Field label={t("ammo.reason")}><input value={f.reason} required maxLength={300} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>}
          {needsAuthority && <Field label={t("ammo.authority")}><input value={f.authority_ref} required maxLength={150} onChange={(e) => setF({ ...f, authority_ref: e.target.value })} /></Field>}
          <button type="submit" disabled={busy || !f.quantity}>{t("ammo.record")}</button>
        </form>
      )}
      <h3>{t("ammo.movements")}</h3>
      <ul className="list">
        {(d?.transactions ?? []).slice().reverse().map((x) => (
          <li key={x.id} className="item">
            <div className="row"><Chip tone={x.delta > 0 ? "approved" : "draft"}>{t(`ammo.kind.${x.kind}` as Key)}</Chip><b>{x.delta > 0 ? `+${x.delta}` : x.delta}</b><span className="muted">→ {x.balance_after}</span></div>
            <p className="muted">{x.at.slice(0, 16).replace("T", " ")} · {x.actor}{x.external_ref ? ` · ${x.external_ref}` : ""}{x.authority_ref ? ` · ${x.authority_ref}` : ""}{x.reason ? ` · ${x.reason}` : ""}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
