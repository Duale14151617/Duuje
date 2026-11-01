import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, Notice, useErrorText } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n, type Key } from "../i18n";

interface Reason { code: string; name_en: string; name_so: string; requires_document: boolean }
interface Rec { id: string; status: string; reason: string | null; note: string; reported_by: string; amended: boolean }
interface RollRow {
  id: string; full_name: string; service_number: string | null; status: string;
  rank: { code: string; name_en: string; name_so: string }; attendance: Rec | null;
}
interface Draft { status: string; reason: string; note: string }
const EMPTY_DRAFT: Draft = { status: "", reason: "", note: "" };
interface Summary { start: string; end: string; days: number; serving: number; present: number; absent: number; on_leave: number; recorded: number; not_recorded: number }

const today = () => new Date().toISOString().slice(0, 10);
const ATT = ["present", "absent", "on_leave"];

/** Daily attendance roll, period summaries and the unit situation report, for authorized commanders (Taliye Guuto / Taliye Urur). */
export function Attendance() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [unit, setUnit] = useState("");
  const [tab, setTab] = useState<"roll" | "summary" | "report">("roll");
  return (
    <>
      <h1>{t("att.title")}</h1>
      <Notice>{t("att.statusNote")}</Notice>
      <section className="card">
        <UnitPicker label={t("pers.unit")} value={unit} onChange={(id) => setUnit(id)} params={{ placeable: 1 }} />
        <div className="row">
          {(["roll", "summary", "report"] as const).map((k) => (
            <button key={k} type="button" className={tab === k ? "" : "secondary"} onClick={() => setTab(k)}>{t(`att.tab.${k}` as Key)}</button>
          ))}
        </div>
      </section>
      {!unit && <p className="muted">{t("att.pickUnit")}</p>}
      {unit && tab === "roll" && <Roll unit={unit} canRecord={can("attendance.record")} />}
      {unit && tab === "summary" && <SummaryTab unit={unit} />}
      {unit && tab === "report" && <ReportTab unit={unit} canSubmit={can("reports.submit")} />}
    </>
  );
}

function Roll({ unit, canRecord }: { unit: string; canRecord: boolean }) {
  const { t, name } = useI18n();
  const errText = useErrorText();
  const [day, setDay] = useState(today());
  const roll = useFetch<{ results: RollRow[] }>("/attendance/roll/", { org_unit: unit, date: day });
  const reasons = useFetch<{ results: Reason[] }>("/attendance/reasons/");
  const [draft, setDraft] = useState<Record<string, Draft>>({});
  const [amending, setAmending] = useState<string | null>(null);
  const [am, setAm] = useState<Draft & { why: string }>({ status: "present", reason: "", note: "", why: "" });
  const [error, setError] = useState<unknown>(null);
  const [rowErrors, setRowErrors] = useState<{ index: number; code: string }[]>([]);
  const [saved, setSaved] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const rows = roll.data?.results ?? [];
  const reasonName = (c: string | null) => { const r = reasons.data?.results.find((x) => x.code === c); return r ? name(r) : ""; };
  const set = (id: string, patch: Partial<Draft>) => setDraft((d) => ({ ...d, [id]: { ...EMPTY_DRAFT, ...d[id], ...patch } }));
  const entries = rows.filter((r) => !r.attendance && draft[r.id]?.status).map((r) => ({ personnel: r.id, ...draft[r.id] }));

  async function save() {
    setBusy(true); setError(null); setRowErrors([]); setSaved(null);
    try {
      const r = await api<{ saved: number }>("/attendance/record/", { method: "POST", body: { org_unit: unit, date: day, entries } });
      setSaved(r.saved); setDraft({}); roll.reload();
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setRowErrors(((err.body as unknown as { rows?: { index: number; code: string }[] })?.rows) ?? []);
    } finally { setBusy(false); }
  }
  async function amend(id: string) {
    setBusy(true); setError(null);
    try {
      await api("/attendance/amend/", { method: "POST", body: { record: id, status: am.status, reason: am.status === "absent" ? am.reason : undefined, note: am.note, amend_reason: am.why } });
      setAmending(null); roll.reload();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const problemText = (code: string) => errText(new ApiError(400, { code }));

  return (
    <section className="card">
      <Field label={t("att.date")}><input type="date" value={day} max={today()} onChange={(e) => { setDay(e.target.value); setDraft({}); }} /></Field>
      <ErrorNotice error={error ?? roll.error} />
      {saved !== null && <Notice>{t("att.saved", { n: saved })}</Notice>}
      {rowErrors.length > 0 && (
        <ul className="list">{rowErrors.map((e, i) => <li key={i} className="item">{entries[e.index] ? rows.find((r) => r.id === entries[e.index].personnel)?.full_name : e.index}: {problemText(e.code)}</li>)}</ul>
      )}
      {canRecord && rows.some((r) => !r.attendance) && (
        <div className="row"><button type="button" className="secondary" onClick={() => setDraft((d) => Object.fromEntries([
          ...Object.entries(d), ...rows.filter((r) => !r.attendance && !d[r.id]?.status).map((r) => [r.id, { status: "present", reason: "", note: "" }])]))}>{t("att.markAllPresent")}</button></div>
      )}
      <ul className="list">
        {rows.map((r) => (
          <li key={r.id} className="item">
            <div className="row">
              <b>{r.rank.code} {r.full_name}</b>
              <Chip tone={r.status === "active" ? "approved" : ["jailed", "suspended"].includes(r.status) ? "bad" : "draft"}>{t(`pstatus.${r.status}` as Key)}</Chip>
            </div>
            {r.attendance ? (
              <>
                <div className="row">
                  <Chip tone={r.attendance.status === "present" ? "approved" : "draft"}>{t(`att.status.${r.attendance.status}` as Key)}</Chip>
                  {r.attendance.amended && <Chip tone="draft">{t("att.amended")}</Chip>}
                  {r.attendance.reason && <span className="muted">{reasonName(r.attendance.reason)}</span>}
                </div>
                <p className="muted">{t("att.recordedBy")}: {r.attendance.reported_by}{r.attendance.note ? ` · ${r.attendance.note}` : ""}</p>
                {canRecord && amending !== r.attendance.id && (
                  <button type="button" className="secondary" onClick={() => { setAmending(r.attendance!.id); setAm({ status: r.attendance!.status, reason: r.attendance!.reason ?? "", note: r.attendance!.note, why: "" }); }}>{t("att.amend")}</button>
                )}
                {amending === r.attendance.id && (
                  <div>
                    <StatusFields value={am} onChange={(p) => setAm({ ...am, ...p })} reasons={reasons.data?.results ?? []} />
                    <Field label={t("att.amendReason")}><input value={am.why} maxLength={300} onChange={(e) => setAm({ ...am, why: e.target.value })} /></Field>
                    <div className="row">
                      <button type="button" disabled={busy || !am.why.trim()} onClick={() => void amend(r.attendance!.id)}>{t("att.amend")}</button>
                      <button type="button" className="secondary" onClick={() => setAmending(null)}>{t("common.cancel")}</button>
                    </div>
                  </div>
                )}
              </>
            ) : canRecord ? (
              <StatusFields value={draft[r.id] ?? { status: "", reason: "", note: "" }} onChange={(p) => set(r.id, p)} reasons={reasons.data?.results ?? []} />
            ) : <span className="muted">{t("att.notRecorded")}</span>}
          </li>
        ))}
      </ul>
      {canRecord && <div className="row"><button type="button" disabled={busy || entries.length === 0} onClick={() => void save()}>{t("att.save")} ({entries.length})</button></div>}
    </section>
  );
}

function StatusFields({ value, onChange, reasons }: { value: Draft; onChange: (p: Partial<Draft>) => void; reasons: Reason[] }) {
  const { t, name } = useI18n();
  return (
    <>
      <select value={value.status} aria-label={t("att.date")} onChange={(e) => onChange({ status: e.target.value })}>
        <option value="">{t("att.notRecorded")}</option>
        {ATT.map((s) => <option key={s} value={s}>{t(`att.status.${s}` as Key)}</option>)}
      </select>
      {value.status === "absent" && (
        <select value={value.reason} aria-label={t("att.reason")} onChange={(e) => onChange({ reason: e.target.value })} required>
          <option value="">{t("att.reason")}</option>
          {reasons.map((r) => <option key={r.code} value={r.code}>{name(r)}</option>)}
        </select>
      )}
      {value.status !== "" && <input value={value.note} maxLength={300} placeholder={t("att.note")} aria-label={t("att.note")} onChange={(e) => onChange({ note: e.target.value })} />}
    </>
  );
}

function SummaryTab({ unit }: { unit: string }) {
  const { t } = useI18n();
  const [kind, setKind] = useState("day");
  const [date, setDate] = useState(today());
  const s = useFetch<Summary>("/attendance/summary/", { org_unit: unit, period: kind, date });
  return (
    <section className="card">
      <div className="grid">
        <Field label={t("att.period")}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {["day", "month", "half", "year"].map((k) => <option key={k} value={k}>{t(`att.${k}` as Key)}</option>)}
          </select>
        </Field>
        <Field label={t("att.date")}><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
      </div>
      <ErrorNotice error={s.error} />
      {s.data && (
        <>
          <p className="muted">{s.data.start} → {s.data.end}</p>
          {(["serving", "present", "absent", "on_leave", "recorded", "not_recorded"] as const).map((k) => (
            <div className="stat" key={k}><span>{t(`att.sum.${k}` as Key)}</span><b>{s.data![k]}</b></div>
          ))}
        </>
      )}
    </section>
  );
}

/** Same periods the server accepts: a whole day, month, half-year (Jan-Jun / Jul-Dec) or year. */
function bounds(kind: string, anchor: string): [string, string] {
  const [y, m] = anchor.split("-").map(Number);
  const iso = (yy: number, mm: number, dd: number) => `${yy}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
  const last = (yy: number, mm: number) => new Date(yy, mm, 0).getDate();
  if (kind === "month") return [iso(y, m, 1), iso(y, m, last(y, m))];
  if (kind === "half") return m <= 6 ? [iso(y, 1, 1), iso(y, 6, 30)] : [iso(y, 7, 1), iso(y, 12, 31)];
  if (kind === "year") return [iso(y, 1, 1), iso(y, 12, 31)];
  return [anchor, anchor];
}

const GROUPS: [Key, string[]][] = [
  ["att.group.personnel", ["personnel_total", "personnel_active", "personnel_on_leave", "personnel_suspended", "personnel_jailed", "personnel_died"]],
  ["att.group.attendance", ["attendance_present", "attendance_absent", "attendance_on_leave", "attendance_not_recorded"]],
  ["att.group.weapons", ["weapons_total", "weapons_in_custody", "weapons_issued", "weapons_returned", "weapons_lost_missing", "weapons_registered", "weapons_condition_changes", "weapons_held_by_non_serving"]],
  ["att.group.recon", ["recon_completed", "recon_variance_lines", "recon_open_discrepancies"]],
  ["att.group.ammo", ["ammo_balance_start", "ammo_opening_recorded", "ammo_received", "ammo_returned", "ammo_adjusted_up", "ammo_issued", "ammo_expended", "ammo_lost_damaged", "ammo_adjusted_down", "ammo_transferred_out", "ammo_remaining"]],
];

function ReportTab({ unit, canSubmit }: { unit: string; canSubmit: boolean }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [kind, setKind] = useState("day");
  const [anchor, setAnchor] = useState(today());
  const [from, to] = bounds(kind, anchor);
  const preview = useFetch<{ figures: Record<string, number> }>("/attendance/situation-preview/", { org_unit: unit, from, to });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function create() {
    setBusy(true); setError(null);
    try {
      const r = await api<{ id: string }>("/attendance/situation-report/", { method: "POST", body: { org_unit: unit, period_start: from, period_end: to } });
      navigate(`/reports/${r.id}`);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <section className="card">
      <div className="grid">
        <Field label={t("att.period")}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {["day", "month", "half", "year"].map((k) => <option key={k} value={k}>{t(`att.${k}` as Key)}</option>)}
          </select>
        </Field>
        <Field label={t("att.date")}><input type="date" value={anchor} onChange={(e) => setAnchor(e.target.value)} /></Field>
      </div>
      <p className="muted">{from} → {to}</p>
      <Notice>{t("att.reportNote")}</Notice>
      <ErrorNotice error={error ?? preview.error} />
      {preview.data && GROUPS.map(([title, keys]) => (
        <div key={title}>
          <h3>{t(title)}</h3>
          {keys.map((k) => <div className="stat" key={k}><span>{t(`fig.${k}` as Key)}</span><b>{preview.data!.figures[k]}</b></div>)}
        </div>
      ))}
      <p className="muted">{t("att.statusAtSubmit")}</p>
      {canSubmit && <div className="row"><button type="button" disabled={busy || !preview.data} onClick={() => void create()}>{t("att.createReport")}</button><Link className="btn secondary" to="/reports">{t("nav.reports")}</Link></div>}
    </section>
  );
}
