import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, PageHeader } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n } from "../i18n";

interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface Rec {
  id: string; register_no: string; org_unit: UnitB | null; detainee_name: string; detainee_alias: string; sex: string; age_years: number | null;
  id_ref: string; address: string; booked_at: string; arrest_place: string; arresting_officer_name: string; reason: string; authority_ref: string;
  cell: string; facility: { id: string; name_en: string; name_so: string } | null; destination_facility: { id: string; name_en: string; name_so: string } | null; property_held: string; health_note: string; status: "in_custody" | "released" | "transferred" | "void"; ended_at: string | null;
  outcome: string; destination: string; outcome_note: string; held_hours: number; overdue: boolean; voided_reason: string; version: number;
  cell_ref: { id: string; code: string } | null; outcome_ref: string; last_review_at: string | null; hours_since_review: number | null;
  received_from: string | null; received_as: string | null; awaiting_receipt: boolean;
}
interface Fac { id: string; kind: "jail_center" | "prison"; name_en: string; name_so: string; org_unit: UnitB | null; status: string; usable: boolean }
interface Cell { id: string; code: string; name: string; capacity: number; occupied: number; available: number; active: boolean }
interface Incoming { id: string; register_no: string; detainee_name: string; from_unit: UnitB | null; to_unit: UnitB | null; booked_at: string; left_at: string; outcome_ref: string; held_hours: number; version: number }
interface Ev { id: string; kind: string; occurred_at: string; text: string; by: string }
interface Detail extends Rec { events: Ev[] }
interface Summary { in_custody: number; overdue: number; booked_today: number; left_today: number; incoming: number; review_hours: number }

const OUTCOMES = ["no_charge", "bail", "court_order", "sentence_served", "transfer_station", "transfer_court", "transfer_prison", "other"];
const EVENT_KINDS = ["welfare", "medical", "visit", "cell_move", "property", "statement", "review", "note"];
const stamp = (s: string | null) => (s ? s.slice(0, 16).replace("T", " ") : "—");
const hours = (h: number) => (h >= 48 ? `${Math.floor(h / 24)}d ${h % 24}h` : `${h}h`);
const clean = (f: Record<string, FormDataEntryValue>) => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== ""));

export function Detention() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const canEdit = can("detention.manage");
  const [status, setStatus] = useState("in_custody");
  const [q, setQ] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [adding, setAdding] = useState(false);
  const [unit, setUnit] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const list = useFetch<Page<Rec>>("/detention/", { status: status || undefined, q: q.trim() || undefined, overdue: overdue ? 1 : undefined, page_size: 100 });
  const summary = useFetch<Summary>("/detention/summary/");
  const detail = useFetch<Detail>(openId ? `/detention/${openId}/` : null);
  const facilities = useFetch<{ results: Fac[] }>("/custody-facilities/", { active: 1 });
  const allFacs = facilities.data?.results ?? [];
  const jails = allFacs.filter((f) => f.kind === "jail_center" && f.org_unit?.id === unit && f.usable);
  const prisons = allFacs.filter((f) => f.kind === "prison" && f.usable);
  const [bookFac, setBookFac] = useState("");
  const [outcome, setOutcome] = useState("");
  const [receiveFac, setReceiveFac] = useState<Record<string, string>>({});
  const bookFacId = bookFac || (jails.length === 1 ? jails[0]!.id : "");
  const bookCells = useFetch<{ results: Cell[] }>(bookFacId ? `/custody-facilities/${bookFacId}/cells/` : null);
  const stations = useFetch<{ results: UnitB[] }>(canEdit ? "/detention/stations/" : null);
  const incoming = useFetch<{ results: Incoming[] }>(canEdit ? "/detention/incoming/" : null);
  const reload = () => { list.reload(); summary.reload(); detail.reload(); incoming.reload(); bookCells.reload(); };

  async function post(path: string, body: Record<string, unknown>): Promise<boolean> {
    setError(null);
    try { await api(path, { method: "POST", body }); reload(); return true; } catch (e) { setError(e); return false; }
  }
  async function book(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const fields = clean(Object.fromEntries(new FormData(form).entries()));
    if (await post("/detention/", { ...fields, org_unit: unit, log_in_ob: fields.log_in_ob === "on" })) { setAdding(false); form.reset(); }
  }
  const row = (x: Rec) => <button type="button" className="secondary" onClick={() => setOpenId(openId === x.id ? null : x.id)}>{openId === x.id ? t("det.hide") : t("det.open")}</button>;

  const cols: Column<Rec>[] = [
    { id: "no", header: t("det.no"), cell: (x) => x.register_no, sort: (x) => x.register_no },
    { id: "name", header: t("det.name"), cell: (x) => x.detainee_name, sort: (x) => x.detainee_name },
    { id: "unit", header: t("det.station"), cell: (x) => (x.org_unit ? name(x.org_unit) : "—") },
    { id: "reason", header: t("det.reason"), cell: (x) => x.reason },
    { id: "booked", header: t("det.booked"), cell: (x) => stamp(x.booked_at), sort: (x) => x.booked_at },
    { id: "held", header: t("det.held"), align: "right", cell: (x) => hours(x.held_hours), sort: (x) => x.held_hours },
    { id: "cell", header: t("det.cell"), cell: (x) => x.cell || "—" },
    { id: "state", header: t("det.state"), cell: (x) => (<>
      <Chip tone={x.status === "in_custody" ? "draft" : x.status === "void" ? "bad" : "approved"}>{t(`det.status.${x.status}` as never)}</Chip>
      {x.overdue && <> <Chip tone="bad">{t("det.overdue")}</Chip></>}
      {x.awaiting_receipt && <> <Chip tone="draft">{t("det.awaitingReceipt")}</Chip></>}</>) },
    { id: "open", header: "", cell: row },
  ];

  const s = summary.data;
  const d = detail.data;
  return (
    <>
      <PageHeader title={t("det.title")} subtitle={t("det.subtitle")}
        actions={canEdit ? <button type="button" onClick={() => setAdding(!adding)}>{t("det.bookIn")}</button> : undefined} />
      {s && <p>{t("det.summary", { held: s.in_custody, overdue: s.overdue, hours: s.review_hours, booked: s.booked_today, left: s.left_today })}{s.incoming ? ` · ${s.incoming} ${t("det.incomingCount")}` : ""}</p>}
      {canEdit && (incoming.data?.results.length ?? 0) > 0 && (
        <section className="card" aria-label={t("det.incoming")}>
          <h3>{t("det.incoming")}</h3>
          <p className="muted">{t("det.incomingHelp")}</p>
          <ul>{incoming.data!.results.map((x) => {
            const dest = allFacs.filter((f) => f.kind === "jail_center" && f.org_unit?.id === x.to_unit?.id && f.usable);
            const chosen = receiveFac[x.id] || (dest.length === 1 ? dest[0]!.id : "");
            return (
              <li key={x.id}>{x.register_no} · <strong>{x.detainee_name}</strong> · {t("det.fromStation")} {x.from_unit ? name(x.from_unit) : "—"} · {t("det.leftAt")} {stamp(x.left_at)}{x.outcome_ref ? ` · ${x.outcome_ref}` : ""}
                {dest.length > 1 && <select aria-label={t("det.facilityPick")} value={chosen} onChange={(e) => setReceiveFac({ ...receiveFac, [x.id]: e.target.value })}><option value="" />{dest.map((f) => <option key={f.id} value={f.id}>{name(f)}</option>)}</select>}
                {" "}<button type="button" onClick={() => void post(`/detention/${x.id}/receive/`, { version: x.version, ...(chosen ? { facility: chosen } : {}) })}>{t("det.receive")}</button></li>);
          })}</ul>
        </section>)}
      <div className="row">
        <Field label={t("det.state")}>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("common.all")}</option>
            {["in_custody", "released", "transferred", "void"].map((k) => <option key={k} value={k}>{t(`det.status.${k}` as never)}</option>)}
          </select>
        </Field>
        <Field label={t("common.search")}><input type="search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={60} /></Field>
        <label className="field"><span>{t("det.overdueOnly")}</span><input type="checkbox" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} /></label>
      </div>
      {error != null && <ErrorNotice error={error} />}
      {adding && (
        <form onSubmit={(e) => void book(e)} className="card">
          <UnitPicker label={t("det.station")} value={unit} onChange={setUnit} required />
          <Field label={t("det.name")}><input name="detainee_name" required maxLength={200} /></Field>
          <Field label={t("det.alias")}><input name="detainee_alias" maxLength={200} /></Field>
          <Field label={t("det.sex")}>
            <select name="sex" defaultValue="unknown"><option value="male">{t("det.sex.male")}</option><option value="female">{t("det.sex.female")}</option><option value="unknown">{t("det.sex.unknown")}</option></select>
          </Field>
          <Field label={t("det.age")}><input name="age_years" type="number" min={0} max={120} inputMode="numeric" /></Field>
          <Field label={t("det.idRef")}><input name="id_ref" maxLength={80} /></Field>
          <Field label={t("det.address")}><input name="address" maxLength={200} /></Field>
          <Field label={t("det.reason")}><input name="reason" required maxLength={300} /></Field>
          <Field label={t("det.authority")}><input name="authority_ref" maxLength={150} /></Field>
          <Field label={t("det.arrestPlace")}><input name="arrest_place" maxLength={200} /></Field>
          <Field label={t("det.officer")}><input name="arresting_officer_name" maxLength={200} /></Field>
          {unit && jails.length === 0 && facilities.data && <p className="muted" role="note">{t("det.noVerifiedJail")}</p>}
          {jails.length > 1 && (
            <Field label={t("det.facilityPick")}><select name="facility" value={bookFac} onChange={(e) => setBookFac(e.target.value)}><option value="" />{jails.map((f) => <option key={f.id} value={f.id}>{name(f)}</option>)}</select></Field>
          )}
          {bookFacId && (bookCells.data?.results.length ?? 0) > 0
            ? <Field label={t("det.cellPick")}><select name="cell_ref" defaultValue=""><option value="">{t("det.noCellChosen")}</option>{bookCells.data!.results.filter((c) => c.active && c.available > 0).map((c) => <option key={c.id} value={c.id}>{c.code}{c.name ? ` · ${c.name}` : ""} ({c.available})</option>)}</select></Field>
            : <Field label={t("det.cell")}><input name="cell" maxLength={60} /></Field>}
          <Field label={t("det.property")}><input name="property_held" maxLength={500} /></Field>
          <Field label={t("det.health")}><input name="health_note" maxLength={300} /></Field>
          <label className="field"><span>{t("det.logInOb")}</span><input name="log_in_ob" type="checkbox" defaultChecked /></label>
          <button type="submit">{t("det.save")}</button>
        </form>
      )}
      <DataTable id="detention" caption={t("det.title")} columns={cols} rows={list.data?.results ?? []} rowKey={(x) => x.id} loading={list.loading} empty={{ title: t("det.empty") }} />
      {openId && d && d.id === openId && (
        <section className="card" aria-label={d.register_no}>
          <h2>{d.register_no} · {d.detainee_name}</h2>
          <p>{[d.sex !== "unknown" ? t(`det.sex.${d.sex}` as never) : "", d.age_years != null ? `${d.age_years}` : "", d.id_ref, d.address].filter(Boolean).join(" · ") || "—"}</p>
          <p><strong>{t("det.reason")}:</strong> {d.reason}{d.authority_ref ? ` (${d.authority_ref})` : ""}</p>
          {d.received_from && <p><strong>{t("det.receivedFrom")}:</strong> {d.received_from}</p>}
          {d.received_as && <p><strong>{t("det.receivedAs")}:</strong> {d.received_as}</p>}
          {d.status === "in_custody" && <p><strong>{t("det.lastReview")}:</strong> {stamp(d.last_review_at)} · {d.hours_since_review ?? 0}h {t("det.sinceReview")}</p>}
          <p><strong>{t("det.booked")}:</strong> {stamp(d.booked_at)}{d.arrest_place ? ` · ${d.arrest_place}` : ""}{d.arresting_officer_name ? ` · ${d.arresting_officer_name}` : ""}</p>
          {(d.facility || d.cell) && <p><strong>{t("det.facility")}:</strong> {[d.facility ? name(d.facility) : "", d.cell].filter(Boolean).join(" · ")}</p>}
          {d.property_held && <p><strong>{t("det.property")}:</strong> {d.property_held}</p>}
          {d.health_note && <p><strong>{t("det.health")}:</strong> {d.health_note}</p>}
          {d.ended_at && <p><strong>{t("det.outcome")}:</strong> {t(`det.outcome.${d.outcome}` as never)}{d.destination ? ` → ${d.destination}` : ""}{d.outcome_ref ? ` · ${d.outcome_ref}` : ""} · {stamp(d.ended_at)}{d.outcome_note ? ` · ${d.outcome_note}` : ""}</p>}
          {d.voided_reason && <p><strong>{t("det.voidedBecause")}:</strong> {d.voided_reason}</p>}
          <h3>{t("det.log")}</h3>
          <ul>{d.events.map((ev) => <li key={ev.id}>{stamp(ev.occurred_at)} · <strong>{t(`det.event.${ev.kind}` as never)}</strong>{ev.text ? ` — ${ev.text}` : ""} <span className="muted">({ev.by})</span></li>)}</ul>
          {canEdit && d.status === "in_custody" && (<>
            <form className="card" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; void post(`/detention/${d.id}/event/`, { version: d.version, ...clean(Object.fromEntries(new FormData(f).entries())) }).then((ok) => ok && f.reset()); }}>
              <Field label={t("det.eventKind")}><select name="kind" defaultValue="welfare">{EVENT_KINDS.map((k) => <option key={k} value={k}>{t(`det.event.${k}` as never)}</option>)}</select></Field>
              <Field label={t("det.eventText")}><input name="text" maxLength={500} /></Field>
              <DetailCellPick facilityId={d.facility?.id ?? null} currentId={d.cell_ref?.id ?? null} />
              <button type="submit">{t("det.addEvent")}</button>
            </form>
            <form className="card" onSubmit={(e) => { e.preventDefault(); void post(`/detention/${d.id}/close/`, { version: d.version, ...clean(Object.fromEntries(new FormData(e.currentTarget).entries())) }); }}>
              <Field label={t("det.outcome")}><select name="outcome" required value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                <option value="" disabled>—</option>{OUTCOMES.map((k) => <option key={k} value={k}>{t(`det.outcome.${k}` as never)}</option>)}</select></Field>
              {outcome === "transfer_station" && (<>
                <Field label={t("det.destStation")}><select name="destination_unit" required defaultValue=""><option value="" disabled>—</option>{(stations.data?.results ?? []).filter((u) => u.id !== d.org_unit?.id).map((u) => <option key={u.id} value={u.id}>{name(u)}</option>)}</select></Field>
                <p className="muted">{t("det.destStationHelp")}</p></>)}
              {outcome === "transfer_prison" && (<>
                <Field label={t("det.destPrison")}><select name="destination_facility" defaultValue=""><option value="">—</option>{prisons.map((f) => <option key={f.id} value={f.id}>{name(f)}</option>)}</select></Field>
                <p className="muted">{t("det.destPrisonHelp")}</p></>)}
              {outcome !== "transfer_station" && <Field label={t("det.destination")}><input name="destination" maxLength={200} /></Field>}
              <Field label={t("det.outcomeRef")}><input name="outcome_ref" maxLength={150} /></Field>
              <Field label={t("det.outcomeNote")}><input name="outcome_note" maxLength={300} /></Field>
              <button type="submit">{t("det.close")}</button>
            </form>
          </>)}
          {canEdit && d.status !== "void" && (
            <button type="button" className="secondary" onClick={() => { const reason = window.prompt(t("det.voidReason")); if (reason) void post(`/detention/${d.id}/void/`, { version: d.version, reason }); }}>{t("det.void")}</button>)}
        </section>
      )}
    </>
  );
}

/** Cell chooser for a cell move: the facility's active cells with room, or a typed cell name when the facility has none. */
function DetailCellPick({ facilityId, currentId }: { facilityId: string | null; currentId: string | null }) {
  const { t } = useI18n();
  const cells = useFetch<{ results: Cell[] }>(facilityId ? `/custody-facilities/${facilityId}/cells/` : null);
  const open = (cells.data?.results ?? []).filter((c) => c.active && c.available > 0 && c.id !== currentId);
  if ((cells.data?.results.length ?? 0) === 0) return <Field label={t("det.newCell")}><input name="cell" maxLength={60} /></Field>;
  return <Field label={t("det.newCell")}><select name="cell_ref" defaultValue=""><option value="" />{open.map((c) => <option key={c.id} value={c.id}>{c.code}{c.name ? ` · ${c.name}` : ""} ({c.available})</option>)}</select></Field>;
}
