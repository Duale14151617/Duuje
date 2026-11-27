import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { UnitPicker } from "../components/UnitPicker";
import { Chip, EmptyState, ErrorNotice, Field, Loading, PageHeader, TabPanel, Tabs, formatDate } from "../components/ui";
import { useI18n } from "../i18n";

interface Named { name_en: string; name_so: string }
interface Person { id: string; full_name: string; service_number: string | null; rank: { code: string } & Named }
interface Category { code: string }
interface EventOut { id: string; name: string; event_date: string; status: "open" | "closed"; org_unit: { code: string } & Named }
interface EventRow { personnel: Person; category: Category & Named; issued: number; returned: number; expended: number; lost: number; outstanding: number }
interface EventSummary { event: EventOut; soldiers: EventRow[]; totals: { issued: number; returned: number; expended: number; lost: number; outstanding: number }; balanced: boolean }
interface Flagged { personnel: Person; category: Category & Named; entries?: number; rounds?: number; unit_median?: number }
interface Flags { days: number; expended_without_event: Flagged[]; heavy_draw: Flagged[]; repeated_loss: Flagged[]; issued_without_lot: Flagged[]; issued_without_event: Flagged[]; events_overdue: EventOut[] }
interface TraceOut {
  weapon: null | {
    serial: string;
    holder_at_time: null | { personnel: Person; issued_at: string; returned_at: string | null; authority_ref: string };
    rounds_held_at_time: { category: Category & Named; rounds: number }[];
    rounds_drawn_in_previous_7_days: { category: Category & Named; rounds: number; reference: string; lot: string; event: string | null; at: string }[];
    custody_chain: { personnel: Person; issued_at: string; returned_at: string | null; outcome: string }[];
  };
  lot: null | { lot: string;
    received: { kind: string; rounds: number; reference: string; at: string; unit: Named; category: Category & Named }[];
    in_store: { unit: Named; category: Category & Named; rounds: number }[];
    issues: { personnel: Person; unit: Named; category: Category & Named; rounds: number; reference: string; event: string | null; at: string }[] };
}

type Tab = "events" | "warnings" | "trace";

const dayOf = (iso: string, lang: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(lang === "so" ? "so-SO" : "en-GB", { dateStyle: "medium" });
const who = (p: Person) => `${p.rank.code} ${p.full_name}${p.service_number ? ` (${p.service_number})` : ""}`;

/** Ammunition control: training events that must balance, warning flags, and the weapon / lot trace. */
export function AmmoControl() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("events");
  const tabs: { id: Tab; label: string }[] = [
    { id: "events", label: t("ac.events") }, { id: "warnings", label: t("ac.warnings") }, { id: "trace", label: t("ac.trace") },
  ];
  return (
    <>
      <PageHeader title={t("nav.ammoControl")} subtitle={t("ac.intro")} />
      <Tabs tabs={tabs} value={tab} onChange={setTab} label={t("nav.ammoControl")} controls idPrefix="acx" />
      <TabPanel id="events" active={tab === "events"} idPrefix="acx"><Events canManage={can("weapons.manage")} /></TabPanel>
      <TabPanel id="warnings" active={tab === "warnings"} idPrefix="acx">{tab === "warnings" && <Warnings />}</TabPanel>
      <TabPanel id="trace" active={tab === "trace"} idPrefix="acx"><Trace /></TabPanel>
    </>
  );
}

function Events({ canManage }: { canManage: boolean }) {
  const { t, lang, name } = useI18n();
  const list = useFetch<{ results: EventOut[] }>("/ammo-control/events/");
  const [openId, setOpenId] = useState("");
  const summary = useFetch<EventSummary>(openId ? "/ammo-control/event/" : null, { id: openId });
  const [form, setForm] = useState({ name: "", event_date: new Date().toISOString().slice(0, 10), org_unit: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function create(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { const ev = await api<EventOut>("/ammo-control/create-event/", { method: "POST", body: form }); setForm({ ...form, name: "" }); list.reload(); setOpenId(ev.id); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  async function close() {
    setBusy(true); setError(null);
    try { await api("/ammo-control/close-event/", { method: "POST", body: { id: openId } }); list.reload(); summary.reload(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  const s = summary.data;
  return (
    <>
      <ErrorNotice error={error ?? list.error ?? summary.error} />
      {canManage && (
        <form className="card" onSubmit={(e) => void create(e)}>
          <h2>{t("ac.new")}</h2>
          <Field label={t("ac.name")}><input value={form.name} required maxLength={150} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label={t("ac.date")}><input type="date" value={form.event_date} required onChange={(e) => setForm({ ...form, event_date: e.target.value })} /></Field>
          <UnitPicker label={t("ac.unit")} value={form.org_unit} required onChange={(id) => setForm({ ...form, org_unit: id })} />
          <div className="row"><button type="submit" disabled={busy || !form.org_unit}>{t("ac.create")}</button></div>
        </form>
      )}
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <EmptyState title={t("ac.noEvents")} />}
      <ul className="list">
        {(list.data?.results ?? []).map((e) => (
          <li key={e.id} className="item">
            <div className="row row-between">
              <div><b>{e.name}</b><div className="muted">{dayOf(e.event_date, lang)} · {name(e.org_unit)}</div></div>
              <div className="row">
                <Chip tone={e.status === "open" ? "warn" : "ok"}>{e.status === "open" ? t("ac.status.open") : t("ac.status.closed")}</Chip>
                <button type="button" className="secondary" onClick={() => setOpenId(openId === e.id ? "" : e.id)}>{t("ac.balance")}</button>
              </div>
            </div>
            {openId === e.id && summary.loading && !s ? <Loading /> : null}
            {openId === e.id && s && (
              <div className="mt-05">
                {s.soldiers.length === 0 ? <p className="muted">{t("ac.nothingDrawn")}</p> : (
                  <table>
                    <thead><tr><th>{t("ac.soldier")}</th><th>{t("ammo.quantity")}</th><th>{t("ac.issued")}</th><th>{t("ac.returned")}</th><th>{t("ac.expended")}</th><th>{t("ac.lost")}</th><th>{t("ac.outstanding")}</th></tr></thead>
                    <tbody>{s.soldiers.map((r, i) => (
                      <tr key={i}><td>{who(r.personnel)}</td><td>{name(r.category)}</td><td>{r.issued}</td><td>{r.returned}</td><td>{r.expended}</td><td>{r.lost}</td>
                        <td><Chip tone={r.outstanding === 0 ? "ok" : "bad"}>{r.outstanding}</Chip></td></tr>
                    ))}</tbody>
                  </table>
                )}
                <p className="muted">{s.balanced ? t("ac.balanced") : t("ac.notBalanced", { n: s.totals.outstanding })}</p>
                {canManage && s.event.status === "open" && <button type="button" disabled={busy || !s.balanced} onClick={() => void close()}>{t("ac.close")}</button>}
              </div>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function FlagList({ title, rows, extra }: { title: string; rows: Flagged[]; extra: (f: Flagged) => string }) {
  const { name } = useI18n();
  if (rows.length === 0) return null;
  return (
    <section className="card">
      <h2>{title}</h2>
      <ul className="list">{rows.map((f, i) => <li key={i} className="item"><b>{who(f.personnel)}</b> <span className="muted">{name(f.category)} · {extra(f)}</span></li>)}</ul>
    </section>
  );
}

function Warnings() {
  const { t, lang, name } = useI18n();
  const f = useFetch<Flags>("/ammo-control/flags/");
  const d = f.data;
  const empty = d && !d.expended_without_event.length && !d.heavy_draw.length && !d.repeated_loss.length && !d.issued_without_lot.length && !d.issued_without_event.length && !d.events_overdue.length;
  return (
    <>
      <ErrorNotice error={f.error} />
      {f.loading && !d ? <Loading /> : null}
      <p className="muted">{t("ac.w.note")}</p>
      {empty && <EmptyState title={t("ac.w.none")} />}
      {d && <>
        <FlagList title={t("ac.w.noEvent")} rows={d.expended_without_event} extra={(x) => t("ac.w.rounds", { n: x.rounds ?? 0 })} />
        <FlagList title={t("ac.w.heavy")} rows={d.heavy_draw} extra={(x) => t("ac.w.vsMedian", { n: x.rounds ?? 0, m: x.unit_median ?? 0 })} />
        <FlagList title={t("ac.w.loss")} rows={d.repeated_loss} extra={(x) => t("ac.w.lossCount", { n: x.entries ?? 0, r: x.rounds ?? 0 })} />
        <FlagList title={t("ac.w.noLot")} rows={d.issued_without_lot} extra={(x) => t("ac.w.drawCount", { n: x.entries ?? 0, r: x.rounds ?? 0 })} />
        <FlagList title={t("ac.w.noEventDraw")} rows={d.issued_without_event} extra={(x) => t("ac.w.drawCount", { n: x.entries ?? 0, r: x.rounds ?? 0 })} />
        {d.events_overdue.length > 0 && (
          <section className="card"><h2>{t("ac.w.overdue")}</h2>
            <ul className="list">{d.events_overdue.map((e) => <li key={e.id} className="item"><b>{e.name}</b> <span className="muted">{dayOf(e.event_date, lang)} · {name(e.org_unit)}</span></li>)}</ul>
          </section>
        )}
      </>}
    </>
  );
}

function Trace() {
  const { t, lang, name } = useI18n();
  const [q, setQ] = useState({ serial: "", lot: "", at: "" });
  const [result, setResult] = useState<TraceOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function go(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      setResult(await api<TraceOut>("/ammo-control/trace/", { query: { serial: q.serial || undefined, lot: q.lot || undefined, at: q.at || undefined } }));
    } catch (err) { setError(err); setResult(null); } finally { setBusy(false); }
  }
  const w = result?.weapon, lot = result?.lot;
  return (
    <>
      <form className="card" onSubmit={(e) => void go(e)}>
        <Field label={t("ac.t.serial")}><input value={q.serial} maxLength={64} onChange={(e) => setQ({ ...q, serial: e.target.value })} /></Field>
        <Field label={t("ac.t.lot")}><input value={q.lot} maxLength={40} onChange={(e) => setQ({ ...q, lot: e.target.value })} /></Field>
        <Field label={t("ac.t.at")}><input type="datetime-local" value={q.at} onChange={(e) => setQ({ ...q, at: e.target.value })} /></Field>
        <div className="row"><button type="submit" disabled={busy || (!q.serial && !q.lot)}>{t("ac.t.go")}</button></div>
        <p className="muted">{t("ac.t.note")}</p>
      </form>
      <ErrorNotice error={error} />
      {result && q.serial && !w && <EmptyState title={t("ac.t.noWeapon")} />}
      {w && (
        <section className="card">
          <h2>{w.serial}</h2>
          {w.holder_at_time
            ? <p><b>{t("ac.t.holder")}:</b> {who(w.holder_at_time.personnel)} <span className="muted">· {formatDate(w.holder_at_time.issued_at, lang)} · {w.holder_at_time.authority_ref}</span></p>
            : <p className="muted">{t("ac.t.noHolder")}</p>}
          {w.rounds_held_at_time.length > 0 && <><h3>{t("ac.t.held")}</h3><ul className="list">{w.rounds_held_at_time.map((r, i) => <li key={i} className="item">{name(r.category)}: {r.rounds}</li>)}</ul></>}
          {w.rounds_drawn_in_previous_7_days.length > 0 && <><h3>{t("ac.t.drawn")}</h3>
            <ul className="list">{w.rounds_drawn_in_previous_7_days.map((r, i) => <li key={i} className="item">{name(r.category)}: {r.rounds} <span className="muted">· {r.reference}{r.lot ? ` · ${t("ac.t.lot")} ${r.lot}` : ""}{r.event ? ` · ${r.event}` : ""} · {formatDate(r.at, lang)}</span></li>)}</ul></>}
          <h3>{t("ac.t.chain")}</h3>
          <ul className="list">{w.custody_chain.map((c, i) => <li key={i} className="item">{who(c.personnel)} <span className="muted">· {formatDate(c.issued_at, lang)} → {c.returned_at ? formatDate(c.returned_at, lang) : "—"}</span></li>)}</ul>
        </section>
      )}
      {lot && (
        <section className="card">
          <h2>{t("ac.t.lot")}: {lot.lot}</h2>
          {lot.received.length > 0 && <><h3>{t("ac.t.received")}</h3>
            <ul className="list">{lot.received.map((r, i) => <li key={i} className="item">{name(r.unit)} · {name(r.category)}: {r.rounds} <span className="muted">· {r.reference} · {formatDate(r.at, lang)}</span></li>)}</ul></>}
          {lot.in_store.length > 0 && <><h3>{t("ac.t.inStore")}</h3>
            <ul className="list">{lot.in_store.map((r, i) => <li key={i} className="item">{name(r.unit)} · {name(r.category)}: {r.rounds}</li>)}</ul></>}
          <h3>{t("ac.t.lotIssues")}</h3>
          {lot.issues.length === 0 ? <p className="muted">{t("ac.t.none")}</p> : (
            <ul className="list">{lot.issues.map((r, i) => <li key={i} className="item"><b>{who(r.personnel)}</b> <span className="muted">· {name(r.unit)} · {name(r.category)}: {r.rounds} · {r.reference}{r.event ? ` · ${r.event}` : ""} · {formatDate(r.at, lang)}</span></li>)}</ul>
          )}
        </section>
      )}
    </>
  );
}
