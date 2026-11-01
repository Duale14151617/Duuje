import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { AppointmentTypeOut, ChangeKind, ChangeRequest, ChangeStatus, PersonLookup } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { UnitPicker } from "../components/UnitPicker";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice } from "../components/ui";
import { useI18n, type Key } from "../i18n";

const BASE = "/organization/change-requests";
const STATUSES: ChangeStatus[] = ["pending", "in_review", "approved", "rejected", "withdrawn"];
const KINDS: ChangeKind[] = ["transfer", "appointment_add", "appointment_end"];

function NewRequest({ onDone }: { onDone: (msg: string) => void }) {
  const { t, name } = useI18n();
  const [kind, setKind] = useState<ChangeKind>("transfer");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => { const h = setTimeout(() => setDebounced(q.trim()), 300); return () => clearTimeout(h); }, [q]);
  const people = useFetch<{ results: PersonLookup[] }>(debounced.length >= 3 ? `${BASE}/people/` : null, { q: debounced });
  const types = useFetch<{ results: AppointmentTypeOut[] }>(kind === "appointment_add" ? `${BASE}/appointment-types/` : null);
  const [person, setPerson] = useState<PersonLookup | null>(null);
  const [unit, setUnit] = useState("");
  const [typeId, setTypeId] = useState("");
  const [appointment, setAppointment] = useState("");
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [orderRef, setOrderRef] = useState("");
  const [officer, setOfficer] = useState("");
  const [orderDate, setOrderDate] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!person) return;
    setError(null); setBusy(true);
    const payload: Record<string, unknown> =
      kind === "transfer" ? { personnel: person.id, org_unit: unit, effective_date: date || undefined, reason }
      : kind === "appointment_add" ? { personnel: person.id, org_unit: unit, appointment_type: typeId, effective_from: date || undefined }
      : { personnel: person.id, appointment, reason };
    try {
      const r = await api<ChangeRequest>(`${BASE}/`, { method: "POST", body: { kind, payload, order_ref: orderRef, issuing_officer: officer, order_date: orderDate } });
      onDone(r.status === "approved" ? t("cr.applied") : t("cr.submitted"));
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h2>{t("cr.new")}</h2>
      <ErrorNotice error={error} />
      <Field label={t("cr.kind")}>
        <select value={kind} onChange={(e) => { setKind(e.target.value as ChangeKind); setUnit(""); setAppointment(""); }}>
          {KINDS.map((k) => <option key={k} value={k}>{t(`cr.kind.${k}` as Key)}</option>)}
        </select>
      </Field>
      <Field label={t("cr.findPerson")}><input type="search" value={q} maxLength={100} onChange={(e) => { setQ(e.target.value); setPerson(null); }} /></Field>
      {people.data && people.data.results.length === 0 && <p className="muted">{t("cr.noMatches")}</p>}
      {!person && (people.data?.results ?? []).map((p) => (
        <button type="button" key={p.id} className="secondary" style={{ display: "block", width: "100%", textAlign: "start", marginBottom: ".25rem" }} onClick={() => setPerson(p)}>
          {p.rank} {p.full_name} · {p.service_number ?? "-"} · {p.unit}
        </button>
      ))}
      {person && <Notice>{t("cr.person")}: {person.rank} {person.full_name} · {person.service_number ?? "-"} · {person.unit}</Notice>}
      {person && kind === "transfer" && (
        <UnitPicker label={t("cr.destination")} value={unit} onChange={setUnit} exclude={person.unit_id} required />
      )}
      {person && kind === "appointment_add" && (
        <>
          <UnitPicker label={t("cr.unit")} value={unit} onChange={setUnit} required />
          <Field label={t("cr.appointmentType")}>
            <select value={typeId} onChange={(e) => setTypeId(e.target.value)} required>
              <option value="" />
              {(types.data?.results ?? []).map((x) => <option key={x.id} value={x.id}>{name(x)}</option>)}
            </select>
          </Field>
        </>
      )}
      {person && kind === "appointment_end" && (
        <Field label={t("cr.appointment")}>
          <select value={appointment} onChange={(e) => setAppointment(e.target.value)} required>
            <option value="" />
            {person.open_appointments.map((a) => <option key={a.id} value={a.id}>{a.type} · {a.unit}</option>)}
          </select>
        </Field>
      )}
      {person && kind !== "appointment_end" && (
        <Field label={t("cr.effectiveFrom")}><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
      )}
      {person && kind !== "appointment_add" && (
        <Field label={t("cr.reason")}><input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} required={kind === "appointment_end"} /></Field>
      )}
      <div className="grid">
        <Field label={t("cr.orderRef")}><input value={orderRef} maxLength={150} onChange={(e) => setOrderRef(e.target.value)} required /></Field>
        <Field label={t("cr.issuingOfficer")}><input value={officer} maxLength={150} onChange={(e) => setOfficer(e.target.value)} required /></Field>
        <Field label={t("cr.orderDate")}><input type="date" value={orderDate} onChange={(e) => setOrderDate(e.target.value)} required /></Field>
      </div>
      <button disabled={busy || !person}>{t("cr.submit")}</button>
    </form>
  );
}

interface BulkRow { row: number; errors: { field: string; code: string }[] }

function BulkTransfer({ onDone }: { onDone: (msg: string) => void }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [unit, setUnit] = useState("");
  const [f, setF] = useState({ order_ref: "", issuing_officer: "", order_date: "", effective_date: "", reason: "" });
  const [error, setError] = useState<unknown>(null);
  const [rows, setRows] = useState<BulkRow[]>([]);
  const numbers = text.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((c) => ({ ...c, [k]: e.target.value }));
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(null); setRows([]);
    try {
      const r = await api<{ count: number }>(`${BASE}/bulk-transfer/`, { method: "POST", body: { ...f, effective_date: f.effective_date || undefined, org_unit: unit, items: numbers.map((service_number) => ({ service_number })) } });
      setText(""); onDone(t("cr.bulkSubmitted", { count: r.count }));
    } catch (err) {
      if (err instanceof ApiError && Array.isArray((err.body as { rows?: BulkRow[] }).rows)) setRows((err.body as { rows: BulkRow[] }).rows);
      else setError(err);
    }
  }
  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h2>{t("cr.bulk")}</h2>
      <p className="muted">{t("cr.bulkHelp")}</p>
      <ErrorNotice error={error} />
      {rows.length > 0 && (
        <Notice kind="error">
          <strong>{t("cr.bulkNothing")}</strong>
          {rows.map((r) => <div key={r.row}>{t("cr.row")} {r.row} ({numbers[r.row - 1] ?? ""}): {r.errors.map((x) => t(`err.${x.code}` as Key)).join(", ")}</div>)}
        </Notice>
      )}
      <Field label={t("cr.serviceNumbers")}><textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} required /></Field>
      <p className="muted">{numbers.length} / 200</p>
      <UnitPicker label={t("cr.destination")} value={unit} onChange={setUnit} required />
      <div className="grid">
        <Field label={t("cr.orderRef")}><input value={f.order_ref} maxLength={150} onChange={set("order_ref")} required /></Field>
        <Field label={t("cr.issuingOfficer")}><input value={f.issuing_officer} maxLength={150} onChange={set("issuing_officer")} required /></Field>
        <Field label={t("cr.orderDate")}><input type="date" value={f.order_date} onChange={set("order_date")} required /></Field>
        <Field label={t("cr.effectiveFrom")}><input type="date" value={f.effective_date} onChange={set("effective_date")} /></Field>
        <Field label={t("cr.reason")}><input value={f.reason} maxLength={200} onChange={set("reason")} /></Field>
      </div>
      <button disabled={numbers.length === 0 || numbers.length > 200}>{t("cr.submit")}</button>
    </form>
  );
}

function BatchCard({ batch, items, onChanged }: { batch: string; items: ChangeRequest[]; onChanged: () => void }) {
  const { t, lang } = useI18n();
  const { me, can } = useAuth();
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const first = items[0];
  const openItems = items.filter((r) => r.status === "pending" || r.status === "in_review");
  const pending = items.filter((r) => r.status === "pending");
  const mine = me?.username === first.proposed_by;
  async function act(action: string, count: number) {
    setError(null);
    try { await api(`${BASE}/batch/`, { method: "POST", body: { batch, action, count, note } }); onChanged(); }
    catch (err) { setError(err); }
  }
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{t("cr.batchOf", { count: items.length })}</strong>
        <Chip tone={first.status}>{t(`cr.status.${first.status}` as Key)}</Chip>
      </div>
      <p className="muted">
        {t("cr.order")}: {first.order_ref} · {first.issuing_officer} · {first.order_date}<br />
        {t("cr.proposedBy")}: {first.proposed_by} · {formatDate(first.created_at, lang)}
        {first.self_approved && <> · {t("cr.selfApproved")}</>}
      </p>
      <details><summary>{t("cr.showPeople")}</summary>{items.map((r) => <div key={r.id} className="muted">{r.summary}</div>)}</details>
      <ErrorNotice error={error} />
      {openItems.length > 0 && (
        <div className="row">
          {can("changes.approve") && !mine && (
            <>
              <input aria-label={t("cr.note")} placeholder={t("cr.note")} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
              {pending.length > 0 && <button className="secondary" onClick={() => void act("start_review", pending.length)}>{t("cr.startReview")}</button>}
              <button onClick={() => void act("approve", openItems.length)}>{t("cr.approveAll")}</button>
              <button className="secondary" onClick={() => void act("reject", openItems.length)}>{t("cr.rejectAll")}</button>
            </>
          )}
          {mine && pending.length === openItems.length && <button className="secondary" onClick={() => void act("withdraw", pending.length)}>{t("cr.withdrawAll")}</button>}
        </div>
      )}
    </div>
  );
}

function Row({ r, onChanged }: { r: ChangeRequest; onChanged: () => void }) {
  const { t, lang } = useI18n();
  const { me, can } = useAuth();
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const open = r.status === "pending" || r.status === "in_review";
  async function act(name: string) {
    setError(null);
    try { await api(`${BASE}/${r.id}/${name}/`, { method: "POST", body: { version: r.version, note } }); onChanged(); }
    catch (err) { setError(err); }
  }
  const mine = me?.username === r.proposed_by;
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{r.summary}</strong>
        <Chip tone={r.status}>{t(`cr.status.${r.status}` as Key)}</Chip>
      </div>
      <p className="muted">
        {t("cr.order")}: {r.order_ref} · {r.issuing_officer} · {r.order_date}<br />
        {t("cr.proposedBy")}: {r.proposed_by} · {formatDate(r.created_at, lang)}
        {r.self_approved && <> · {t("cr.selfApproved")}</>}
        {r.decision_note && <><br />{r.decided_by}: {r.decision_note}</>}
      </p>
      <ErrorNotice error={error} />
      {open && !r.batch && (
        <div className="row">
          {can("changes.approve") && !mine && (
            <>
              <input aria-label={t("cr.note")} placeholder={t("cr.note")} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
              {r.status === "pending" && <button className="secondary" onClick={() => void act("start-review")}>{t("cr.startReview")}</button>}
              <button onClick={() => void act("approve")}>{t("cr.approve")}</button>
              <button className="secondary" onClick={() => void act("reject")}>{t("cr.reject")}</button>
            </>
          )}
          {mine && r.status === "pending" && <button className="secondary" onClick={() => void act("withdraw")}>{t("cr.withdraw")}</button>}
        </div>
      )}
    </div>
  );
}

/** Requests entered together on one order are shown (and decided) as one batch; the rest stand alone. Order is kept. */
function groups(rows: ChangeRequest[]): { batch: string | null; items: ChangeRequest[] }[] {
  const out: { batch: string | null; items: ChangeRequest[] }[] = [];
  const seen = new Map<string, { batch: string | null; items: ChangeRequest[] }>();
  for (const r of rows) {
    if (!r.batch) { out.push({ batch: null, items: [r] }); continue; }
    let g = seen.get(r.batch);
    if (!g) { g = { batch: r.batch, items: [] }; seen.set(r.batch, g); out.push(g); }
    g.items.push(r);
  }
  return out;
}

export function ChangeRequests() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [msg, setMsg] = useState("");
  const list = useFetch<{ results: ChangeRequest[] }>(`${BASE}/`, { status });
  return (
    <main>
      <h1>{t("cr.title")}</h1>
      <p className="muted">{t("cr.intro")}</p>
      {msg && <Notice>{msg}</Notice>}
      {can("changes.propose") && <NewRequest onDone={(m) => { setMsg(m); list.reload(); }} />}
      {can("changes.propose") && <BulkTransfer onDone={(m) => { setMsg(m); list.reload(); }} />}
      <Field label={t("cr.status")}>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("cr.all")}</option>
          {STATUSES.map((s) => <option key={s} value={s}>{t(`cr.status.${s}` as Key)}</option>)}
        </select>
      </Field>
      {list.loading ? <Loading /> : <ErrorNotice error={list.error} />}
      {list.data?.results.length === 0 && <p className="muted">{t("cr.empty")}</p>}
      {groups(list.data?.results ?? []).map((g) => g.batch
        ? <BatchCard key={g.batch} batch={g.batch} items={g.items} onChanged={list.reload} />
        : <Row key={g.items[0].id} r={g.items[0]} onChanged={list.reload} />)}
    </main>
  );
}
