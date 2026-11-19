import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, Notice, PageHeader, TabPanel, Tabs } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n, type Key } from "../i18n";

interface Named { code: string; name_en: string; name_so: string }
interface LeaveRow {
  id: string; personnel: { id: string; full_name: string; service_number: string | null }; org_unit: Named & { id: string };
  leave_type: Named; start_date: string; end_date: string; days: number; reason: string;
  status: "pending" | "approved" | "rejected" | "cancelled"; requested_by: string; decided_by: string; decision_note: string;
}
interface LeaveType extends Named { max_days: number | null }
interface RosterPerson { id: string; full_name: string; service_number: string | null }
interface RosterData {
  people: RosterPerson[]; shifts: { personnel: string; date: string; shift: string }[];
  leave: { personnel: string; from: string; to: string; type: string }[];
}

const SHIFTS = ["day", "night", "standby", "off"] as const;
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (s: string, n: number) => { const d = new Date(`${s}T00:00:00`); d.setDate(d.getDate() + n); return iso(d); };
const mondayOf = (d: Date) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return iso(x); };

/** Leave requests (ask, approve, reject, cancel) and the weekly duty roster. Neither touches personnel status or attendance. */
export function Leave() {
  const { t } = useI18n();
  const { can } = useAuth();
  const showRoster = can("roster.view");
  const [tab, setTab] = useState<"requests" | "roster">("requests");
  return (
    <>
      <PageHeader title={t("lv.title")} subtitle={t("lv.subtitle")} />
      {showRoster && <Tabs label={t("lv.title")} value={tab} onChange={setTab} controls idPrefix="lv"
        tabs={[{ id: "requests", label: t("lv.tab.requests") }, { id: "roster", label: t("lv.tab.roster") }]} />}
      <TabPanel id="requests" active={tab === "requests"} idPrefix="lv"><Requests /></TabPanel>
      <TabPanel id="roster" active={tab === "roster" && showRoster} idPrefix="lv"><Roster /></TabPanel>
    </>
  );
}

function Requests() {
  const { t, lang, name } = useI18n();
  const { can, me } = useAuth();
  const canAsk = can("leave.request"), canDecide = can("leave.approve");
  const [onlyMine, setOnlyMine] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState(false);
  const [unit, setUnit] = useState("");
  const [who, setWho] = useState("");
  const types = useFetch<{ results: LeaveType[] }>("/leave/types/");
  const list = useFetch<{ results: LeaveRow[] }>("/leave/", { mine: onlyMine ? 1 : undefined, status: status || undefined });
  const people = useFetch<RosterData>(canAsk && can("roster.view") && unit ? "/roster/" : null, { org_unit: unit });
  const day = (s: string) => new Date(`${s}T00:00:00`).toLocaleDateString(lang === "so" ? "so-SO" : "en-GB", { dateStyle: "medium" });

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = Object.fromEntries(new FormData(form).entries());
    setError(null); setSent(false);
    try {
      await api("/leave/", { method: "POST", body: { ...f, personnel: who || undefined } });
      form.reset(); setSent(true); list.reload();
    } catch (err) { setError(err); }
  }
  async function act(r: LeaveRow, verb: "approve" | "reject" | "cancel", note?: string) {
    setError(null);
    try { await api(`/leave/${r.id}/${verb}/`, { method: "POST", body: note ? { note } : {} }); }
    catch (err) { setError(err); }
    list.reload();
  }

  return (
    <>
      <ErrorNotice error={error} />
      {sent && <Notice>{t("lv.sent")}</Notice>}
      <section className="card" aria-label={t("lv.new")}>
        <h3>{t("lv.new")}</h3>
        <form onSubmit={(e) => void send(e)}>
          {canAsk && can("roster.view") && (
            <>
              <UnitPicker label={t("lv.roster.unit")} value={unit} onChange={(id) => { setUnit(id); setWho(""); }} allowAll />
              {unit && (
                <Field label={t("lv.person")}>
                  <select value={who} onChange={(e) => setWho(e.target.value)}>
                    <option value="">{t("lv.self")}</option>
                    {(people.data?.people ?? []).map((p) => <option key={p.id} value={p.id}>{p.full_name}{p.service_number ? ` · ${p.service_number}` : ""}</option>)}
                  </select>
                </Field>)}
            </>)}
          <Field label={t("lv.type")}>
            <select name="leave_type" required defaultValue="">
              <option value="" />
              {(types.data?.results ?? []).map((x) => <option key={x.code} value={x.code}>{name(x)}</option>)}
            </select>
          </Field>
          <div className="row">
            <Field label={t("lv.from")}><input type="date" name="start_date" required /></Field>
            <Field label={t("lv.to")}><input type="date" name="end_date" required /></Field>
          </div>
          <Field label={t("lv.reason")}><input name="reason" maxLength={300} /></Field>
          <button type="submit">{t("lv.submit")}</button>
        </form>
      </section>

      <section className="card" aria-label={t("lv.tab.requests")}>
        <h3>{t("lv.tab.requests")}</h3>
        <div className="row">
          <Field label={t("lv.status")}>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("common.all")}</option>
              {(["pending", "approved", "rejected", "cancelled"] as const).map((s) => <option key={s} value={s}>{t(`lv.status.${s}` as Key)}</option>)}
            </select>
          </Field>
          {canDecide && <label className="field"><span>{t("lv.onlyMine")}</span>
            <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} /></label>}
        </div>
        {list.data && list.data.results.length === 0 && <p className="muted">{t("common.empty")}</p>}
        <ul className="list">
          {(list.data?.results ?? []).map((r) => {
            const mine = r.personnel.id === me?.personnel_id;
            return (
              <li key={r.id} className="item">
                <div className="row">
                  <b>{r.personnel.full_name}</b>
                  <span>{name(r.leave_type)} · {day(r.start_date)} – {day(r.end_date)} · {t("lv.days", { n: r.days })}</span>
                  <Chip tone={r.status === "approved" ? "approved" : r.status === "pending" ? "draft" : r.status === "rejected" ? "bad" : "neutral"}>{t(`lv.status.${r.status}` as Key)}</Chip>
                </div>
                <p className="muted">{name(r.org_unit)} · {t("lv.askedBy", { by: r.requested_by })}{r.decided_by ? ` · ${t("lv.decidedBy", { by: r.decided_by })}` : ""}</p>
                {r.reason && <p>{r.reason}</p>}
                {r.decision_note && <p className="muted">{r.decision_note}</p>}
                {r.status === "pending" && canDecide && !mine && <DecideForm onApprove={() => act(r, "approve")} onReject={(n) => act(r, "reject", n)} />}
                {(r.status === "pending" || r.status === "approved") && (mine || canAsk || canDecide) && (
                  <button type="button" className="secondary" onClick={() => void act(r, "cancel")}>{t("lv.cancel")}</button>)}
              </li>);
          })}
        </ul>
      </section>
    </>
  );
}

function DecideForm({ onApprove, onReject }: { onApprove: () => Promise<void>; onReject: (note: string) => Promise<void> }) {
  const { t } = useI18n();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const run = (f: () => Promise<void>) => { setBusy(true); void f().finally(() => setBusy(false)); };
  return (
    <div className="row mt-1">
      <Field label={t("lv.note")}><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
      <button type="button" disabled={busy} onClick={() => run(onApprove)}>{t("lv.approve")}</button>
      <button type="button" className="secondary" disabled={busy} onClick={() => run(() => onReject(note.trim()))}>{t("lv.reject")}</button>
    </div>
  );
}

function Roster() {
  const { t, lang } = useI18n();
  const { can } = useAuth();
  const canManage = can("roster.manage");
  const [unit, setUnit] = useState("");
  const [week, setWeek] = useState(mondayOf(new Date()));
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const to = addDays(week, 6);
  const data = useFetch<RosterData>(unit ? "/roster/" : null, { org_unit: unit, from: week, to });
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(week, i)), [week]);
  const current = useMemo(() => new Map((data.data?.shifts ?? []).map((s) => [`${s.personnel}|${s.date}`, s.shift])), [data.data]);
  const onLeave = (pid: string, d: string) => (data.data?.leave ?? []).some((l) => l.personnel === pid && l.from <= d && d <= l.to);
  const head = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString(lang === "so" ? "so-SO" : "en-GB", { weekday: "short", day: "numeric", month: "short" });

  async function save() {
    const entries = Object.entries(edits).map(([k, shift]) => { const [personnel, date] = k.split("|"); return { personnel, date, shift }; });
    if (entries.length === 0) return;
    setError(null); setSaved(false);
    try {
      await api("/roster/assign/", { method: "POST", body: { org_unit: unit, entries } });
      setEdits({}); setSaved(true); data.reload();
    } catch (err) { setError(err); }
  }

  return (
    <>
      <ErrorNotice error={error} />
      {saved && <Notice>{t("lv.roster.saved")}</Notice>}
      <section className="card" aria-label={t("lv.tab.roster")}>
        <UnitPicker label={t("lv.roster.unit")} value={unit} onChange={(id) => { setUnit(id); setEdits({}); }} />
        <Field label={t("lv.roster.week")}>
          <input type="date" value={week} onChange={(e) => { if (e.target.value) { setWeek(mondayOf(new Date(`${e.target.value}T00:00:00`))); setEdits({}); } }} />
        </Field>
        {!unit && <p className="muted">{t("lv.roster.pick")}</p>}
        {unit && data.data && data.data.people.length === 0 && <p className="muted">{t("lv.roster.nobody")}</p>}
        {unit && data.data && data.data.people.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>{t("lv.roster.person")}</th>{days.map((d) => <th key={d}>{head(d)}</th>)}</tr></thead>
              <tbody>
                {data.data.people.map((p) => (
                  <tr key={p.id}>
                    <td>{p.full_name}</td>
                    {days.map((d) => {
                      const key = `${p.id}|${d}`, was = current.get(key) ?? "";
                      if (onLeave(p.id, d)) return <td key={d}><Chip tone="warn">{t("lv.onLeave")}</Chip></td>;
                      const value = edits[key] ?? was;
                      return (
                        <td key={d}>
                          <select aria-label={`${p.full_name} ${head(d)}`} value={value} disabled={!canManage}
                                  onChange={(e) => setEdits((m) => (e.target.value === was ? Object.fromEntries(Object.entries(m).filter(([k]) => k !== key)) : { ...m, [key]: e.target.value }))}>
                            <option value="" disabled={was !== ""}>{t("lv.shift.none")}</option>
                            {SHIFTS.map((s) => <option key={s} value={s}>{t(`lv.shift.${s}` as Key)}</option>)}
                          </select>
                        </td>);
                    })}
                  </tr>))}
              </tbody>
            </table>
          </div>)}
        {canManage && unit && <button type="button" disabled={Object.keys(edits).length === 0} onClick={() => void save()}>{t("lv.roster.save")}</button>}
      </section>
    </>
  );
}
