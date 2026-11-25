import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n } from "../i18n";
import { formatDateTime } from "../lib/format";

interface Person { id: string; full_name: string; username: string }
interface Sched {
  id: string; name: string; enabled: boolean; version: number; org_unit: { id: string; code: string; name_en: string; name_so: string };
  frequency: "daily" | "weekly" | "monthly"; weekday: number; day_of_month: number; send_hour: number; period_days: number;
  recipients: Person[]; next_run_at: string | null; last_run_at: string | null; last_status: string; last_detail: string; timezone: string;
}
interface Form { id: string | null; version: number; name: string; unit: string; frequency: "daily" | "weekly" | "monthly"; weekday: number; day: number; hour: number; period: number; recipients: string[] }

const BLANK: Form = { id: null, version: 1, name: "", unit: "", frequency: "weekly", weekday: 0, day: 1, hour: 7, period: 7, recipients: [] };

const L = {
  en: {
    title: "Scheduled reports", subtitle: "Email the personnel strength report to commanders on a timetable. Counts only: no names or service numbers.",
    off: "Scheduled reports are switched off on this server.", new: "New schedule", edit: "Edit schedule", name: "Name", unit: "Area (this unit and everything below it)",
    freq: "How often", daily: "Every day", weekly: "Every week", monthly: "Every month", on: "On", at: "At (hour)", period: "Movement window (days): joined, left, promoted",
    recipients: "Recipients", noRecipients: "Choose an area first. Only people with a verified email who can view this area's personnel report are listed.",
    save: "Save schedule", saving: "Saving...", cancel: "Cancel", list: "Schedules", none: "No schedules yet.", next: "Next", last: "Last", never: "not yet", paused: "Paused",
    pause: "Pause", resume: "Resume", test: "Send test to me", sendAll: "Send now to everyone", del: "Delete", confirmDel: "Delete this schedule?",
    confirmSend: "Send the report now to every recipient?", tz: "Times are in", sent: "Done", days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    st: { sent: "Sent", partial: "Partly sent", failed: "Failed", no_access: "Creator lost access", no_recipients: "No eligible recipient", email_not_configured: "Email not set up", disabled: "Switched off" } as Record<string, string>,
  },
  so: {
    title: "Warbixinno la jadwaleeyay", subtitle: "U dir warbixinta xooggga shaqaalaha taliyayaasha iimayl si joogto ah. Tiro kaliya: magac ama lambarka shaqada lagama dirayo.",
    off: "Warbixinnada la jadwaleeyay waa xiran yihiin server-kan.", new: "Jadwal cusub", edit: "Wax ka beddel jadwalka", name: "Magac", unit: "Aagga (cutubkan iyo wax kasta oo ka hooseeya)",
    freq: "Inta jeer", daily: "Maalin walba", weekly: "Toddobaad walba", monthly: "Bil walba", on: "Maalinta", at: "Saacadda", period: "Muddada dhaqdhaqaaqa (maalmo): ku biiray, ka baxay, kor loo qaaday",
    recipients: "Helayaasha", noRecipients: "Marka hore dooro aag. Waxaa la tusayaa kaliya dadka iimayl la xaqiijiyay leh oo arki kara warbixinta aagga.",
    save: "Kaydi jadwalka", saving: "Waa la kaydinayaa...", cancel: "Jooji", list: "Jadwalada", none: "Jadwal weli ma jiro.", next: "Xiga", last: "Kii ugu dambeeyay", never: "weli", paused: "La hakiyay",
    pause: "Hakad", resume: "Sii wad", test: "Isiidir tijaabo", sendAll: "Hadda u dir dhammaan", del: "Tirtir", confirmDel: "Tirtir jadwalkan?",
    confirmSend: "Hadda u dir warbixinta dhammaan helayaasha?", tz: "Waqtiyadu waa", sent: "Waa dhammaaday", days: ["Isniin", "Talaado", "Arbaco", "Khamiis", "Jimce", "Sabti", "Axad"],
    st: { sent: "La diray", partial: "Qayb la diray", failed: "Waa fashilmay", no_access: "Abuuruhu marin gelidda wuu waayay", no_recipients: "Helaye ma jiro", email_not_configured: "Iimayl lama dejin", disabled: "Waa xiran yahay" } as Record<string, string>,
  },
} as const;

function fmt(iso: string | null, lang: string, never: string): string {
  if (!iso) return never;
  return formatDateTime(iso, lang);
}

/** Create and manage emailed reports (the weekly strength report to commanders, for example). */
export function Schedules() {
  const { lang, name } = useI18n();
  const s = L[lang === "so" ? "so" : "en"];
  const list = useFetch<{ results: Sched[]; enabled: boolean }>("/schedules/");
  const [form, setForm] = useState<Form | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [msg, setMsg] = useState("");
  const unit = form?.unit ?? "";

  useEffect(() => {
    let live = true;
    if (!unit) { setPeople([]); return; }
    api<{ results: Person[] }>("/schedules/recipients/", { query: { unit } })
      .then((r) => { if (live) setPeople(r.results); })
      .catch(() => { if (live) setPeople([]); });
    return () => { live = false; };
  }, [unit]);

  const patch = (p: Partial<Form>) => setForm((f) => (f ? { ...f, ...p } : f));
  const toggle = (id: string) => setForm((f) => (f ? { ...f, recipients: f.recipients.includes(id) ? f.recipients.filter((x) => x !== id) : [...f.recipients, id] } : f));

  function load(x: Sched) {
    setErr(null); setMsg("");
    setForm({ id: x.id, version: x.version, name: x.name, unit: x.org_unit.id, frequency: x.frequency, weekday: x.weekday, day: x.day_of_month, hour: x.send_hour, period: x.period_days, recipients: x.recipients.map((r) => r.id) });
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy("save"); setErr(null);
    const body = { name: form.name, org_unit: form.unit, frequency: form.frequency, weekday: form.weekday, day_of_month: form.day, send_hour: form.hour, period_days: form.period, recipients: form.recipients };
    try {
      if (form.id) await api(`/schedules/${form.id}/`, { method: "PATCH", body: { ...body, version: form.version } });
      else await api("/schedules/", { method: "POST", body });
      setForm(null); list.reload();
    } catch (x) { setErr(x); } finally { setBusy(null); }
  }

  async function act(id: string, what: "toggle" | "test" | "all" | "delete", x: Sched) {
    if (what === "delete" && !window.confirm(s.confirmDel)) return;
    if (what === "all" && !window.confirm(s.confirmSend)) return;
    setBusy(id); setErr(null); setMsg("");
    try {
      if (what === "toggle") await api(`/schedules/${id}/`, { method: "PATCH", body: { version: x.version, enabled: !x.enabled } });
      else if (what === "delete") await api(`/schedules/${id}/remove/`, { method: "POST" });
      else {
        const r = await api<{ status: string; detail: string }>(`/schedules/${id}/send-now/`, { method: "POST", body: { to_me: what === "test" } });
        setMsg(`${s.st[r.status] ?? r.status}: ${r.detail}`);
      }
      list.reload();
    } catch (z) { setErr(z); } finally { setBusy(null); }
  }

  const weekly = form?.frequency === "weekly";
  const monthly = form?.frequency === "monthly";
  return (
    <>
      <PageHeader title={s.title} subtitle={s.subtitle} actions={!form ? <button type="button" onClick={() => { setErr(null); setMsg(""); setForm({ ...BLANK }); }}>{s.new}</button> : undefined} />
      {list.data && !list.data.enabled && <Notice kind="warn">{s.off}</Notice>}
      <ErrorNotice error={list.error} />
      {msg && <Notice kind="info">{msg}</Notice>}
      {form && (
        <section className="card">
          <h2>{form.id ? s.edit : s.new}</h2>
          <form onSubmit={(e) => void save(e)}>
            <Field label={s.name}><input value={form.name} maxLength={120} required onChange={(e) => patch({ name: e.target.value })} /></Field>
            {form.id ? null : <UnitPicker label={s.unit} value={form.unit} onChange={(id) => patch({ unit: id, recipients: [] })} required />}
            <Field label={s.freq}>
              <select value={form.frequency} onChange={(e) => patch({ frequency: e.target.value as Form["frequency"] })}>
                <option value="daily">{s.daily}</option><option value="weekly">{s.weekly}</option><option value="monthly">{s.monthly}</option>
              </select>
            </Field>
            {weekly && <Field label={s.on}><select value={form.weekday} onChange={(e) => patch({ weekday: Number(e.target.value) })}>{s.days.map((d, i) => <option key={d} value={i}>{d}</option>)}</select></Field>}
            {monthly && <Field label={s.on}><select value={form.day} onChange={(e) => patch({ day: Number(e.target.value) })}>{Array.from({ length: 28 }, (_, i) => i + 1).map((d) => <option key={d} value={d}>{d}</option>)}</select></Field>}
            <Field label={s.at}><select value={form.hour} onChange={(e) => patch({ hour: Number(e.target.value) })}>{Array.from({ length: 24 }, (_, i) => i).map((h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}</select></Field>
            <Field label={s.period}><input type="number" min={1} max={90} value={form.period} onChange={(e) => patch({ period: Math.max(1, Math.min(90, Number(e.target.value) || 1)) })} /></Field>
            <fieldset>
              <legend>{s.recipients}</legend>
              {people.length === 0 ? <p className="muted">{s.noRecipients}</p> : people.map((p) => (
                <label key={p.id} className="row" style={{ gap: ".5rem" }}>
                  <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={form.recipients.includes(p.id)} onChange={() => toggle(p.id)} />
                  <span>{p.full_name} <span className="muted">({p.username})</span></span>
                </label>
              ))}
            </fieldset>
            <ErrorNotice error={err} />
            <div className="row">
              <button type="submit" disabled={busy === "save" || !form.unit}>{busy === "save" ? s.saving : s.save}</button>
              <button type="button" className="secondary" onClick={() => { setForm(null); setErr(null); }}>{s.cancel}</button>
            </div>
          </form>
        </section>
      )}
      <section className="card">
        <h2>{s.list}</h2>
        {!form && <ErrorNotice error={err} />}
        {list.loading && !list.data ? <Loading /> : (list.data?.results.length ?? 0) === 0 ? <p className="muted">{s.none}</p> : list.data?.results.map((x) => (
          <div key={x.id} className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <b>{x.name}</b>{!x.enabled && <span className="chip warn">{s.paused}</span>}
            </div>
            <p className="muted">
              {name(x.org_unit)} · {x.frequency === "daily" ? s.daily : x.frequency === "weekly" ? `${s.weekly}, ${s.days[x.weekday]}` : `${s.monthly}, ${x.day_of_month}`} · {String(x.send_hour).padStart(2, "0")}:00 ({s.tz} {x.timezone})
            </p>
            <p>{x.recipients.map((r) => r.full_name).join(", ") || "-"}</p>
            <p className="muted">{s.next}: {x.enabled ? fmt(x.next_run_at, lang, s.never) : "-"} · {s.last}: {fmt(x.last_run_at, lang, s.never)}{x.last_status ? ` (${s.st[x.last_status] ?? x.last_status})` : ""}</p>
            {x.last_detail && x.last_status !== "sent" && <p className="muted">{x.last_detail}</p>}
            <div className="row">
              <button type="button" className="secondary sm" onClick={() => load(x)}>{s.edit}</button>
              <button type="button" className="secondary sm" disabled={busy === x.id} onClick={() => void act(x.id, "toggle", x)}>{x.enabled ? s.pause : s.resume}</button>
              <button type="button" className="secondary sm" disabled={busy === x.id} onClick={() => void act(x.id, "test", x)}>{s.test}</button>
              <button type="button" className="secondary sm" disabled={busy === x.id} onClick={() => void act(x.id, "all", x)}>{s.sendAll}</button>
              <button type="button" className="secondary sm" disabled={busy === x.id} onClick={() => void act(x.id, "delete", x)}>{s.del}</button>
            </div>
          </div>
        ))}
      </section>
    </>
  );
}
