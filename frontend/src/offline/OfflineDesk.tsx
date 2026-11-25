import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Field, Notice, PageHeader } from "../components/ui";
import { useI18n } from "../i18n";
import { lastAssigned, offlineEventKinds, syncQueue } from "./sync";
import * as vault from "./vault";
import type { QueueItem, Snapshot } from "./vault";
import { formatDateTime } from "../lib/format";

interface Fac { kind: string; usable: boolean; org_unit: { id: string; name_en: string; name_so: string } | null }
interface Rec { id: string; register_no: string; detainee_name: string }

const clean = (o: Record<string, FormDataEntryValue>) => Object.fromEntries(Object.entries(o).filter(([, v]) => String(v).trim() !== ""));
const newId = () => crypto.randomUUID();

/**
 * Offline desk: enter bookings and custody-log entries with no connection, then send them when the network returns.
 * Works from the sign-in screen too (the app shell is kept by the service worker), because an officer may open it with no signal.
 */
export function OfflineDesk() {
  const { t, lang } = useI18n();
  const { me } = useAuth();
  const [ready, setReady] = useState<"loading" | "none" | "locked" | "open">("loading");
  const [items, setItems] = useState<QueueItem[]>([]);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [msg, setMsg] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);

  useEffect(() => {
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);

  const refresh = useCallback(async () => {
    if (!vault.supported()) { setReady("none"); return; }
    if (!(await vault.exists())) { setReady("none"); return; }
    if (!vault.isUnlocked()) { setReady("locked"); return; }
    setItems(await vault.listItems());
    setSnap(await vault.loadSnapshot());
    setReady("open");
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  async function setup(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const a = String(f.get("pass") ?? ""), b = String(f.get("pass2") ?? "");
    if (a.length < vault.MIN_PASSPHRASE) { setMsg({ kind: "error", text: t("off.passShort", { n: vault.MIN_PASSPHRASE }) }); return; }
    if (a !== b) { setMsg({ kind: "error", text: t("off.passMismatch") }); return; }
    setBusy(true);
    try { await vault.create(a); setMsg(null); await refresh(); } catch { setMsg({ kind: "error", text: t("off.failed") }); } finally { setBusy(false); }
  }
  async function unlock(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    try {
      const ok = await vault.unlock(String(new FormData(e.currentTarget).get("pass") ?? ""));
      setMsg(ok ? null : { kind: "error", text: t("off.wrongPass") });
      if (ok) await refresh();
    } finally { setBusy(false); }
  }

  /** Download the lists the officer needs while offline (needs a connection and a signed-in session). */
  async function download() {
    setBusy(true);
    try {
      const [facs, held] = await Promise.all([
        api<{ results: Fac[] }>("/custody-facilities/", { query: { active: 1, kind: "jail_center" } }),
        api<{ results: Rec[] }>("/detention/", { query: { status: "in_custody", page_size: 100 } }),
      ]);
      const seen = new Map<string, { id: string; name: string }>();
      for (const f of facs.results) if (f.usable && f.org_unit) seen.set(f.org_unit.id, { id: f.org_unit.id, name: lang === "so" ? f.org_unit.name_so : f.org_unit.name_en });
      const next: Snapshot = {
        taken_at: new Date().toISOString(), stations: [...seen.values()],
        in_custody: held.results.map((r) => ({ id: r.id, register_no: r.register_no, detainee_name: r.detainee_name })),
      };
      await vault.saveSnapshot(next);
      setSnap(next);
      setMsg({ kind: "info", text: t("off.downloaded", { s: next.stations.length, p: next.in_custody.length }) });
    } catch { setMsg({ kind: "error", text: t("off.downloadFailed") }); } finally { setBusy(false); }
  }

  async function addBooking(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const b = clean(Object.fromEntries(new FormData(form).entries()));
    if (!b.org_unit) { setMsg({ kind: "error", text: t("off.needStation") }); return; }
    const stamp = new Date().toISOString();
    await vault.putItem({ id: newId(), kind: "booking", created_at: stamp, state: "pending", label: `${t("off.kindBooking")}: ${String(b.detainee_name)}`, payload: { ...b, booked_at: stamp } });
    form.reset(); setMsg({ kind: "info", text: t("off.saved") }); await refresh();
  }
  async function addEvent(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const b = clean(Object.fromEntries(new FormData(form).entries()));
    const person = snap?.in_custody.find((p) => p.id === b.target);
    if (!person) { setMsg({ kind: "error", text: t("off.needPerson") }); return; }
    const stamp = new Date().toISOString();
    await vault.putItem({
      id: newId(), kind: "event", created_at: stamp, state: "pending", target: person.id, target_label: `${person.register_no} ${person.detainee_name}`,
      label: `${t(`det.event.${String(b.kind)}` as never)}: ${person.register_no} ${person.detainee_name}`,
      payload: { kind: b.kind, text: b.text ?? "", occurred_at: stamp },
    });
    form.reset(); setMsg({ kind: "info", text: t("off.saved") }); await refresh();
  }
  async function sync() {
    setBusy(true); lastAssigned.length = 0;
    try {
      const r = await syncQueue(() => void refresh());
      await refresh();
      if (r.stopped === "network") setMsg({ kind: "error", text: t("off.stillOffline", { n: r.sent }) });
      else if (r.stopped === "auth") setMsg({ kind: "error", text: t("off.signIn") });
      else setMsg({ kind: r.attention ? "error" : "info", text: t("off.synced", { sent: r.sent, attention: r.attention }) });
    } finally { setBusy(false); }
  }
  async function discard(i: QueueItem) {
    if (!window.confirm(t("off.discardConfirm"))) return;
    await vault.removeItem(i.id); await refresh();
  }
  async function wipe() {
    if (!window.confirm(t(items.length ? "off.wipeConfirmPending" : "off.wipeConfirm", { n: items.length }))) return;
    await vault.wipe(); setItems([]); setSnap(null); setMsg(null); await refresh();
  }

  const header = <PageHeader title={t("off.title")} subtitle={t("off.subtitle")} />;
  const warning = <Notice>{t("off.clockNote")}</Notice>;
  const status = <p className="muted" role="status">{online ? t("off.online") : t("off.offline")}</p>;
  const note = msg && <Notice kind={msg.kind}>{msg.text}</Notice>;

  if (ready === "loading") return <main>{header}</main>;
  if (ready === "none") return (
    <main>{header}{status}{note}
      {!vault.supported() ? <Notice kind="error">{t("off.unsupported")}</Notice> : (
        <form className="card" onSubmit={(e) => void setup(e)}>
          <p>{t("off.prepareHelp")}</p>
          {!online && <Notice kind="error">{t("off.prepareOnline")}</Notice>}
          <Field label={t("off.pass")}><input name="pass" type="password" autoComplete="new-password" minLength={vault.MIN_PASSPHRASE} required /></Field>
          <Field label={t("off.pass2")}><input name="pass2" type="password" autoComplete="new-password" required /></Field>
          <p className="muted">{t("off.passWarn")}</p>
          <button type="submit" disabled={busy || !online}>{t("off.prepare")}</button>
        </form>)}
      {!me && <p><Link to="/">{t("off.backToSignIn")}</Link></p>}
    </main>);
  if (ready === "locked") return (
    <main>{header}{status}{note}
      <form className="card" onSubmit={(e) => void unlock(e)}>
        <Field label={t("off.pass")}><input name="pass" type="password" autoComplete="current-password" required /></Field>
        <button type="submit" disabled={busy}>{t("off.unlock")}</button>{" "}
        <button type="button" className="secondary" onClick={() => void wipe()}>{t("off.forgot")}</button>
      </form>
      {!me && <p><Link to="/">{t("off.backToSignIn")}</Link></p>}
    </main>);

  return (
    <main>{header}{status}{warning}{note}
      {lastAssigned.length > 0 && (
        <Notice><strong>{t("off.assigned")}</strong><ul>{lastAssigned.map((a, i) => <li key={i}>{a.label} → <strong>{a.no}</strong></li>)}</ul></Notice>)}
      <section className="card">
        <h2>{t("off.queue")} ({items.length})</h2>
        {items.length === 0 ? <p className="muted">{t("off.queueEmpty")}</p> : (
          <ul>{items.map((i) => (
            <li key={i.id}>
              {i.label} <span className="muted">· {formatDateTime(i.created_at, lang)}</span>
              {i.state === "attention" && <div role="alert"><strong>{t("off.attention")}:</strong> {i.problem}</div>}
              {" "}<button type="button" className="secondary" onClick={() => void discard(i)}>{t("off.discard")}</button>
            </li>))}</ul>)}
        <button type="button" disabled={busy || !online || !me || items.every((i) => i.state !== "pending")} onClick={() => void sync()}>{t("off.sync")}</button>
        {!me && <p className="muted">{t("off.signInToSync")} <Link to="/">{t("off.backToSignIn")}</Link></p>}
      </section>
      <section className="card">
        <p className="muted">{snap ? t("off.snapshotAt", { when: formatDateTime(snap.taken_at, lang), s: snap.stations.length, p: snap.in_custody.length }) : t("off.noSnapshot")}</p>
        <button type="button" className="secondary" disabled={busy || !online || !me} onClick={() => void download()}>{t("off.download")}</button>
      </section>
      <form className="card" onSubmit={(e) => void addBooking(e)}>
        <h2>{t("off.newBooking")}</h2>
        <Field label={t("det.station")}><select name="org_unit" required defaultValue=""><option value="" />{snap?.stations.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        <Field label={t("det.name")}><input name="detainee_name" required maxLength={200} /></Field>
        <Field label={t("det.sex")}><select name="sex" defaultValue="unknown"><option value="male">{t("det.sex.male")}</option><option value="female">{t("det.sex.female")}</option><option value="unknown">{t("det.sex.unknown")}</option></select></Field>
        <Field label={t("det.age")}><input name="age_years" type="number" min={0} max={120} inputMode="numeric" /></Field>
        <Field label={t("det.idRef")}><input name="id_ref" maxLength={80} /></Field>
        <Field label={t("det.address")}><input name="address" maxLength={200} /></Field>
        <Field label={t("det.reason")}><input name="reason" required maxLength={300} /></Field>
        <Field label={t("det.authority")}><input name="authority_ref" maxLength={150} /></Field>
        <Field label={t("det.arrestPlace")}><input name="arrest_place" maxLength={200} /></Field>
        <Field label={t("det.officer")}><input name="arresting_officer_name" maxLength={200} /></Field>
        <Field label={t("det.property")}><input name="property_held" maxLength={500} /></Field>
        <Field label={t("det.health")}><input name="health_note" maxLength={300} /></Field>
        <p className="muted">{t("off.bookingNote")}</p>
        <button type="submit">{t("off.saveOnDevice")}</button>
      </form>
      <form className="card" onSubmit={(e) => void addEvent(e)}>
        <h2>{t("off.newEntry")}</h2>
        <Field label={t("off.person")}><select name="target" required defaultValue=""><option value="" />{snap?.in_custody.map((p) => <option key={p.id} value={p.id}>{p.register_no} · {p.detainee_name}</option>)}</select></Field>
        <Field label={t("det.eventKind")}><select name="kind" defaultValue="welfare">{offlineEventKinds.map((k) => <option key={k} value={k}>{t(`det.event.${k}` as never)}</option>)}</select></Field>
        <Field label={t("det.eventText")}><input name="text" maxLength={500} /></Field>
        <p className="muted">{t("off.entryNote")}</p>
        <button type="submit">{t("off.saveOnDevice")}</button>
      </form>
      <p>
        <button type="button" className="secondary" onClick={() => { vault.lock(); void refresh(); }}>{t("off.lock")}</button>{" "}
        <button type="button" className="secondary" onClick={() => void wipe()}>{t("off.wipe")}</button>
      </p>
    </main>);
}
