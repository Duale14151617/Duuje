import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Page } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { ExportPdfButton, type PdfContent } from "../components/ExportPdfButton";
import { EmptyState, Chip, ErrorNotice, Field, formatDate, Notice, PageHeader } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n } from "../i18n";

interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface Person { register_no: string; name: string; cell: string; held_hours: number; review_due: boolean; court_soon: boolean; remand_expired: boolean }
interface Note {
  id: string; org_unit: UnitB | null; shift_ended_at: string; custody: Person[]; custody_note: string; pending: string; watch: string;
  written_by: string; written_at: string; acknowledged: { by: string; at: string; comment: string } | null; ack_overdue: boolean;
}
interface Waiting { waiting: number; for_me: number; overdue: number; results: Note[] }
interface Preview { org_unit: UnitB; custody: Person[]; blocked_by: Note | null }

/** Shift handover: one note at the end of a shift (who is held, what is pending, what to watch) that the next officer must acknowledge. */
export function ShiftHandover() {
  const { t, lang, name } = useI18n();
  const { can, me } = useAuth();
  const canWrite = can("detention.manage");
  const [unit, setUnit] = useState("");
  const [onlyWaiting, setOnlyWaiting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const waiting = useFetch<Waiting>("/shift-handovers/waiting/");
  const list = useFetch<Page<Note>>("/shift-handovers/", { waiting: onlyWaiting ? 1 : undefined, page_size: 50 });
  const preview = useFetch<Preview>(canWrite && unit ? "/shift-handovers/preview/" : null, { unit });
  const reload = () => { waiting.reload(); list.reload(); preview.reload(); };
  const stamp = (s: string) => formatDate(s, lang);

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = Object.fromEntries(new FormData(form).entries());
    setError(null); setSent(false);
    try {
      await api("/shift-handovers/", { method: "POST", body: { ...f, org_unit: unit } });
      form.reset(); setSent(true); reload();
    } catch (err) { setError(err); }
  }
  async function acknowledge(n: Note, comment: string) {
    setError(null); setSent(false);
    try { await api(`/shift-handovers/${n.id}/acknowledge/`, { method: "POST", body: comment ? { comment } : {} }); reload(); }
    catch (err) { setError(err); reload(); }
  }
  const flags = (p: Person) => [p.review_due && t("hnd.flag.review"), p.court_soon && t("hnd.flag.court"), p.remand_expired && t("hnd.flag.remand")].filter(Boolean).join(", ");

  const noteDoc = (n: Note): PdfContent => ({
    title: t("hnd.pdfTitle"),
    subtitle: `${n.org_unit ? name(n.org_unit) : ""} · ${t("hnd.shiftEnd")}: ${stamp(n.shift_ended_at)} · ${t("hnd.writtenBy", { by: n.written_by, at: stamp(n.written_at) })}`,
    sections: [
      { heading: t("hnd.custodyNow"), columns: [{ header: t("hnd.reg"), width: 2 }, { header: t("hnd.name"), width: 4 }, { header: t("hnd.cell"), width: 2 }, { header: t("hnd.held"), width: 1 }, { header: t("hnd.flags"), width: 3 }],
        rows: n.custody.map((p) => [p.register_no, p.name, p.cell, `${p.held_hours} h`, flags(p)]) },
      ...(n.custody_note ? [{ heading: t("hnd.custodyNote"), columns: [{ header: "", width: 1 }], rows: [[n.custody_note]] }] : []),
      { heading: t("hnd.pending"), columns: [{ header: "", width: 1 }], rows: [[n.pending]] },
      { heading: t("hnd.watch"), columns: [{ header: "", width: 1 }], rows: [[n.watch]] },
      { columns: [{ header: "", width: 1 }], rows: [[n.acknowledged ? t("hnd.ackedBy", { by: n.acknowledged.by, at: stamp(n.acknowledged.at) }) : t("hnd.notAcked")]] },
    ],
  });

  const people = (rows: Person[]) => rows.length === 0 ? <p className="muted">{t("hnd.nobody")}</p> : (
    <ul className="list">
      {rows.map((p) => (
        <li key={p.register_no} className="item">
          <b>{p.register_no}</b> · {p.name}{p.cell ? <> · {t("hnd.cell")} {p.cell}</> : null} · {p.held_hours} h
          {flags(p) ? <> <Chip tone="bad">{flags(p)}</Chip></> : null}
        </li>))}
    </ul>);

  function card(n: Note, canAck: boolean) {
    const open = openId === n.id || canAck;
    const mine = n.written_by === me?.username;
    return (
      <li key={n.id} className="item">
        <div className="row">
          <b>{n.org_unit ? name(n.org_unit) : "—"}</b>
          <span>{t("hnd.writtenBy", { by: n.written_by, at: stamp(n.written_at) })}</span>
          {n.acknowledged ? <Chip tone="approved">{t("hnd.ackedBy", { by: n.acknowledged.by, at: stamp(n.acknowledged.at) })}</Chip>
            : <Chip tone={n.ack_overdue ? "bad" : "draft"}>{n.ack_overdue ? t("hnd.overdue") : t("hnd.notAcked")}</Chip>}
          {!canAck && <button type="button" className="secondary" onClick={() => setOpenId(openId === n.id ? null : n.id)}>{open ? t("hnd.hide") : t("hnd.show")}</button>}
        </div>
        {open && (
          <div className="mt-1">
            <h4>{t("hnd.custodyNow")}</h4>
            {people(n.custody)}
            {n.custody_note && <><h4>{t("hnd.custodyNote")}</h4><p>{n.custody_note}</p></>}
            <h4>{t("hnd.pending")}</h4><p>{n.pending}</p>
            <h4>{t("hnd.watch")}</h4><p>{n.watch}</p>
            {n.acknowledged?.comment && <p className="muted">{n.acknowledged.comment}</p>}
            {mine && !n.acknowledged && <p className="muted">{t("hnd.ownNote")}</p>}
            <div className="row"><ExportPdfButton label={t("hnd.print")} filename={`handover-${n.org_unit?.code ?? "note"}`} build={() => noteDoc(n)} /></div>
          </div>)}
        {canAck && <AckForm onAck={(c) => acknowledge(n, c)} />}
      </li>);
  }

  const mustAck = waiting.data?.results ?? [];
  return (
    <>
      <PageHeader title={t("hnd.title")} subtitle={t("hnd.subtitle")} />
      <ErrorNotice error={error} />
      {sent && <Notice>{t("hnd.sent")}</Notice>}

      <section className="card" aria-label={t("hnd.waiting")}>
        <h3>{t("hnd.waiting")}</h3>
        {mustAck.length === 0 ? <p className="muted">{t("hnd.noneWaiting")}</p> : <ul className="list">{mustAck.map((n) => card(n, true))}</ul>}
      </section>

      {canWrite && (
        <section className="card" aria-label={t("hnd.write")}>
          <h3>{t("hnd.write")}</h3>
          <UnitPicker label={t("hnd.station")} value={unit} onChange={setUnit} required />
          {unit && preview.data && (
            <>
              {preview.data.blocked_by && <Notice kind="error">{t("hnd.blocked", { by: preview.data.blocked_by.written_by })}</Notice>}
              <h4>{t("hnd.custodyNow")}</h4>
              {people(preview.data.custody)}
              <form onSubmit={(e) => void send(e)}>
                <Field label={t("hnd.shiftEnd")}><input type="datetime-local" name="shift_ended_at" /></Field>
                <Field label={t("hnd.custodyNote")}><textarea name="custody_note" maxLength={1000} rows={3} /></Field>
                <Field label={t("hnd.pending")}><textarea name="pending" maxLength={2000} rows={4} required /></Field>
                <Field label={t("hnd.watch")}><textarea name="watch" maxLength={2000} rows={4} required /></Field>
                <p className="muted">{t("hnd.requiredHint")}</p>
                <button type="submit" disabled={!!preview.data.blocked_by}>{t("hnd.submit")}</button>
              </form>
            </>)}
        </section>)}

      <section className="card" aria-label={t("hnd.history")}>
        <h3>{t("hnd.history")}</h3>
        <label className="field"><span>{t("hnd.onlyWaiting")}</span>
          <input type="checkbox" checked={onlyWaiting} onChange={(e) => setOnlyWaiting(e.target.checked)} /></label>
        {list.data && list.data.results.length === 0 && <EmptyState compact icon="swap" title={t("common.empty")} hint={t("common.emptyHint")} />}
        <ul className="list">{(list.data?.results ?? []).map((n) => card(n, false))}</ul>
      </section>
    </>
  );
}

function AckForm({ onAck }: { onAck: (comment: string) => Promise<void> }) {
  const { t } = useI18n();
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="row mt-1">
      <Field label={t("hnd.ackComment")}><input value={comment} maxLength={300} onChange={(e) => setComment(e.target.value)} /></Field>
      <button type="button" disabled={busy} onClick={() => { setBusy(true); void onAck(comment.trim()).finally(() => setBusy(false)); }}>{t("hnd.ack")}</button>
    </div>
  );
}
