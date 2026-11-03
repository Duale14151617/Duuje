import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { UnitPicker } from "../components/UnitPicker";
import { Chip, ErrorNotice, Field, formatDate, Loading, Notice } from "../components/ui";
import { useI18n } from "../i18n";

interface Progress { pending: number; verified: number; missing: number; mismatch: number; unlisted: number; total: number }
interface Count {
  id: string; kind: string; status: string; note: string; org_unit: { id: string; code: string; name_en: string; name_so: string };
  opened_by: string; opened_at: string; submitted_by: string; signed_by: string; signed_at: string | null; sign_note: string; progress: Progress;
}
interface Line {
  id: string; expected_identifier: string; expected_type: string; expected_holder: string; expected_status: string;
  result: string; observed_identifier: string; note: string; checked_by: string;
}

const L = {
  en: {
    title: "Weapon inventory", note: "A physical count of every serial-numbered weapon a unit should hold. Someone checks each serial number against the register, a different person signs the count off, and every shortage or mismatch must be explained first. A count never changes the weapon register.",
    start: "Start a count", unit: "Unit", kind: "Kind of count", cyclic: "Scheduled (cyclic)", change_of_command: "Change of command", spot: "Spot check", remark: "Note (optional)", create: "Start",
    none: "No counts yet.", checked: "checked", open: "Open", submitted: "Waiting for sign-off", signed: "Signed off", cancelled: "Cancelled",
    back: "Back", view: "Open", opened: "Opened", by: "by", pending: "Not checked", verified: "Verified", missing: "Missing", mismatch: "Different serial", unlisted: "Found, not listed",
    verify: "Verified", markMissing: "Missing", markMismatch: "Different serial", askSerial: "Serial number actually read off the item:", askNote: "Explanation (what happened to it, who was told):",
    explain: "Explain", addFound: "Add an item found that is not on the list", askFound: "Serial number of the item found:", submit: "Submit the count", sign: "Sign off", cancel: "Cancel the count",
    confirmSubmit: "Submit this count? You cannot change the checks afterwards.", confirmSign: "Sign off this count?", confirmCancel: "Cancel this count?", signNote: "Sign-off note (optional):",
    holder: "Expected with", serial: "Serial", type: "Item", result: "Result", needSign: "A different person must sign this off.", signedBy: "Signed off by",
  },
  so: {
    title: "Tirinta hubka", note: "Tiris jireed ah oo hubka lambarka taxan leh ee cutubku haysto. Qof ayaa lambar kasta ku hubiya diiwaanka, qof kale ayaa saxiixaya, shaqo kasta oo la waayay ama is-ma-laha waa in la sharaxaa marka hore. Tiristu ma beddesho diiwaanka hubka.",
    start: "Bilow tiris", unit: "Cutubka", kind: "Nooca tirinta", cyclic: "Joogto (jadwal)", change_of_command: "Beddelka taliska", spot: "Hubin degdeg ah", remark: "Faallo (ikhtiyaari)", create: "Bilow",
    none: "Weli tiris ma jirto.", checked: "la hubiyay", open: "Furan", submitted: "Sugaya saxiixa", signed: "La saxiixay", cancelled: "La joojiyay",
    back: "Dib", view: "Fur", opened: "La furay", by: "ka", pending: "Lama hubin", verified: "La xaqiijiyay", missing: "La waayay", mismatch: "Lambar kale", unlisted: "La helay, lama qorin",
    verify: "La xaqiijiyay", markMissing: "La waayay", markMismatch: "Lambar kale", askSerial: "Lambarka dhabta ah ee laga akhriyay shayga:", askNote: "Sharaxaad (maxaa dhacay, yaa la ogeysiiyay):",
    explain: "Sharax", addFound: "Ku dar shay la helay oo aan liiska ku jirin", askFound: "Lambarka shayga la helay:", submit: "Gudbi tirinta", sign: "Saxiix", cancel: "Jooji tirinta",
    confirmSubmit: "Ma gudbisaa tirintan? Kadib hubinta lama beddeli karo.", confirmSign: "Ma saxiixaysaa tirintan?", confirmCancel: "Ma joojisaa tirintan?", signNote: "Qoraalka saxiixa (ikhtiyaari):",
    holder: "Waxaa la filayay inuu la jiro", serial: "Lambar", type: "Shay", result: "Natiijo", needSign: "Qof kale ayaa waa inuu saxiixaa.", signedBy: "Waxaa saxiixay",
  },
};
type S = typeof L.en;
const tone = (r: string) => (r === "verified" ? "ok" : r === "pending" ? "neutral" : r === "missing" ? "bad" : "warn");
const statusTone = (s: string) => (s === "signed" ? "ok" : s === "cancelled" ? "neutral" : s === "submitted" ? "info" : "warn");

function Start({ s, onDone }: { s: S; onDone: (id: string) => void }) {
  const [unit, setUnit] = useState("");
  const [kind, setKind] = useState("cyclic");
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  async function go(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try { onDone((await api<Count>("/inventories/", { method: "POST", body: { org_unit: unit, kind, note } })).id); } catch (err) { setError(err); }
  }
  return (
    <form className="card" onSubmit={(e) => void go(e)}>
      <h2>{s.start}</h2>
      <ErrorNotice error={error} />
      <UnitPicker label={s.unit} value={unit} onChange={(id) => setUnit(id)} required />
      <Field label={s.kind}>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="cyclic">{s.cyclic}</option><option value="change_of_command">{s.change_of_command}</option><option value="spot">{s.spot}</option>
        </select>
      </Field>
      <Field label={s.remark}><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
      <button type="submit" disabled={!unit}>{s.create}</button>
    </form>
  );
}

function Detail({ id, s, onBack }: { id: string; s: S; onBack: () => void }) {
  const { lang, name } = useI18n();
  const { can } = useAuth();
  const data = useFetch<Count & { lines: Line[] }>(`/inventories/${id}/`);
  const [error, setError] = useState<unknown>(null);
  const c = data.data;
  const manage = can("weapons.manage");

  async function post(path: string, body: Record<string, unknown>) {
    setError(null);
    try { await api(`/inventories/${id}/${path}/`, { method: "POST", body }); data.reload(); } catch (err) { setError(err); }
  }
  function check(line: Line, result: string) {
    const body: Record<string, unknown> = { line: line.id, result };
    if (result === "mismatch") {
      const serial = window.prompt(s.askSerial);
      if (!serial) return;
      body.observed_identifier = serial.trim();
    }
    if (result !== "verified") { const note = window.prompt(s.askNote); if (note) body.note = note; }
    void post("check", body);
  }
  function explain(line: Line) {
    const note = window.prompt(s.askNote, line.note);
    if (note !== null) void post("annotate", { line: line.id, note });
  }
  function found() {
    const serial = window.prompt(s.askFound);
    if (serial) void post("found", { identifier: serial.trim() });
  }

  if (data.loading && !c) return <Loading />;
  if (!c) return <ErrorNotice error={data.error} />;
  const p = c.progress;
  const live = c.status === "open";
  return (
    <>
      <button type="button" className="secondary sm" onClick={onBack}>← {s.back}</button>
      <div className="card" style={{ marginTop: ".75rem" }}>
        <h2 style={{ marginTop: 0 }}>{name(c.org_unit)} <Chip tone={statusTone(c.status)}>{s[c.status as "open"]}</Chip></h2>
        <p className="muted">{s[c.kind as "cyclic"]} · {s.opened} {formatDate(c.opened_at, lang)} {s.by} {c.opened_by}{c.signed_by ? ` · ${s.signedBy} ${c.signed_by}` : ""}</p>
        <p>{p.total - p.pending} / {p.total} {s.checked} · <Chip tone="ok">{p.verified}</Chip> <Chip tone="bad">{p.missing}</Chip> <Chip tone="warn">{p.mismatch + p.unlisted}</Chip></p>
        <ErrorNotice error={error || data.error} />
        {c.status === "submitted" && <Notice>{s.needSign}</Notice>}
        {manage && (
          <div className="row">
            {live && <button type="button" className="secondary" onClick={found}>{s.addFound}</button>}
            {live && <button type="button" disabled={p.pending > 0} onClick={() => { if (window.confirm(s.confirmSubmit)) void post("submit", {}); }}>{s.submit}</button>}
            {c.status === "submitted" && <button type="button" onClick={() => { if (window.confirm(s.confirmSign)) void post("sign", { note: window.prompt(s.signNote) ?? "" }); }}>{s.sign}</button>}
            {(live || c.status === "submitted") && <button type="button" className="secondary" onClick={() => { if (window.confirm(s.confirmCancel)) void post("cancel", {}); }}>{s.cancel}</button>}
          </div>
        )}
      </div>
      <ul className="list">
        {c.lines.map((ln) => (
          <li className="item" key={ln.id}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong className="mono">{ln.expected_identifier || ln.observed_identifier}</strong>
              <Chip tone={tone(ln.result)}>{s[ln.result as "pending"]}</Chip>
            </div>
            <p className="muted">{ln.expected_type}{ln.expected_holder ? ` · ${s.holder}: ${ln.expected_holder}` : ""}</p>
            {ln.result === "mismatch" && <p>{s.mismatch}: <span className="mono">{ln.observed_identifier}</span></p>}
            {ln.note && <p className="muted">{ln.note}</p>}
            {manage && live && ln.result !== "unlisted" && (
              <div className="row">
                <button type="button" className="secondary sm" onClick={() => check(ln, "verified")}>{s.verify}</button>
                <button type="button" className="secondary sm" onClick={() => check(ln, "missing")}>{s.markMissing}</button>
                <button type="button" className="secondary sm" onClick={() => check(ln, "mismatch")}>{s.markMismatch}</button>
              </div>
            )}
            {manage && (live || c.status === "submitted") && ln.result !== "verified" && ln.result !== "pending" && (
              <button type="button" className="secondary sm" onClick={() => explain(ln)}>{s.explain}</button>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

export function Inventories() {
  const { lang, name } = useI18n();
  const { can } = useAuth();
  const s = L[lang === "so" ? "so" : "en"];
  const list = useFetch<Count[]>("/inventories/");
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  if (selected) return <Detail id={selected} s={s} onBack={() => { setSelected(null); list.reload(); }} />;
  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0 }}>{s.title}</h1>
        {can("weapons.manage") && !adding && <button type="button" onClick={() => setAdding(true)}>{s.start}</button>}
      </div>
      <Notice>{s.note}</Notice>
      {adding && <Start s={s} onDone={(id) => { setAdding(false); setSelected(id); }} />}
      <ErrorNotice error={list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.length === 0 && <p className="muted">{s.none}</p>}
      <ul className="list">
        {list.data?.map((c) => (
          <li className="item" key={c.id}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3 style={{ margin: 0 }}>{name(c.org_unit)}</h3>
              <Chip tone={statusTone(c.status)}>{s[c.status as "open"]}</Chip>
            </div>
            <p className="muted">{s[c.kind as "cyclic"]} · {formatDate(c.opened_at, lang)} · {c.progress.total - c.progress.pending} / {c.progress.total} {s.checked}</p>
            <button type="button" className="secondary sm" onClick={() => setSelected(c.id)}>{s.view}</button>
          </li>
        ))}
      </ul>
    </>
  );
}
