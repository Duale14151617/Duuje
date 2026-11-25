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
interface Entry {
  id: string; ob_number: string; org_unit: UnitB | null; category: string; occurred_at: string; location: string; reported_by: string;
  summary: string; details: string; detention: { id: string; register_no: string } | null; status: "recorded" | "void"; recorded_by: string;
  voided_reason: string; version: number;
}
interface FollowUp { id: string; kind: string; occurred_at: string; text: string; by: string }
interface Detail extends Entry { follow_ups: FollowUp[] }
interface Summary { today: number; this_year: number; arrests_today: number }

const CATEGORIES = ["complaint", "arrest", "incident", "accident", "theft_loss", "found_property", "custody", "patrol", "duty_change", "visitor", "other"];
const FOLLOW_KINDS = ["update", "correction", "outcome"];
const stamp = (s: string | null) => (s ? s.slice(0, 16).replace("T", " ") : "—");
const clean = (f: Record<string, FormDataEntryValue>) => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== ""));

export function OccurrenceBook() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const canEdit = can("detention.manage");
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [unit, setUnit] = useState("");
  const [filterUnit, setFilterUnit] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const list = useFetch<Page<Entry>>("/occurrence-book/", { category: category || undefined, q: q.trim() || undefined, unit: filterUnit || undefined, page_size: 100 });
  const summary = useFetch<Summary>("/occurrence-book/summary/");
  const detail = useFetch<Detail>(openId ? `/occurrence-book/${openId}/` : null);
  const reload = () => { list.reload(); summary.reload(); detail.reload(); };

  async function post(path: string, body: Record<string, unknown>): Promise<boolean> {
    setError(null);
    try { await api(path, { method: "POST", body }); reload(); return true; } catch (e) { setError(e); return false; }
  }
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    if (await post("/occurrence-book/", { ...clean(Object.fromEntries(new FormData(form).entries())), org_unit: unit })) { setAdding(false); form.reset(); }
  }
  const cat = (k: string) => t(`ob.cat.${k}` as never);
  const open = (x: Entry) => <button type="button" className="secondary" onClick={() => setOpenId(openId === x.id ? null : x.id)}>{openId === x.id ? t("ob.hide") : t("ob.open")}</button>;

  const cols: Column<Entry>[] = [
    { id: "no", header: t("ob.no"), cell: (x) => x.ob_number, sort: (x) => x.ob_number },
    { id: "unit", header: t("ob.station"), cell: (x) => (x.org_unit ? name(x.org_unit) : "—") },
    { id: "when", header: t("ob.when"), cell: (x) => stamp(x.occurred_at), sort: (x) => x.occurred_at },
    { id: "cat", header: t("ob.category"), cell: (x) => cat(x.category) },
    { id: "sum", header: t("ob.entrySummary"), cell: (x) => x.summary },
    { id: "state", header: t("ob.status"), cell: (x) => <Chip tone={x.status === "void" ? "bad" : "approved"}>{t(`ob.status.${x.status}` as never)}</Chip> },
    { id: "open", header: "", cell: open },
  ];

  const s = summary.data;
  const d = detail.data;
  return (
    <>
      <PageHeader title={t("ob.title")} subtitle={t("ob.subtitle")}
        actions={canEdit ? <button type="button" onClick={() => setAdding(!adding)}>{t("ob.add")}</button> : undefined} />
      {s && <p>{t("ob.summary", { today: s.today, arrests: s.arrests_today, year: s.this_year })}</p>}
      <div className="row">
        <Field label={t("ob.category")}>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">{t("common.all")}</option>
            {CATEGORIES.map((k) => <option key={k} value={k}>{cat(k)}</option>)}
          </select>
        </Field>
        <Field label={t("common.search")}><input type="search" value={q} onChange={(e) => setQ(e.target.value)} maxLength={60} /></Field>
        <UnitPicker label={t("ob.station")} value={filterUnit} onChange={setFilterUnit} allowAll />
      </div>
      {error != null && <ErrorNotice error={error} />}
      {adding && (
        <form onSubmit={(e) => void add(e)} className="card">
          <UnitPicker label={t("ob.station")} value={unit} onChange={setUnit} required />
          <Field label={t("ob.category")}>
            <select name="category" required defaultValue="complaint">{CATEGORIES.map((k) => <option key={k} value={k}>{cat(k)}</option>)}</select>
          </Field>
          <Field label={t("ob.when")}><input name="occurred_at" type="datetime-local" /></Field>
          <Field label={t("ob.entrySummary")}><input name="summary" required maxLength={300} /></Field>
          <Field label={t("ob.details")}><textarea name="details" rows={4} maxLength={3000} /></Field>
          <Field label={t("ob.location")}><input name="location" maxLength={200} /></Field>
          <Field label={t("ob.reportedBy")}><input name="reported_by" maxLength={200} /></Field>
          <button type="submit">{t("ob.save")}</button>
        </form>
      )}
      <DataTable id="occurrence-book" caption={t("ob.title")} columns={cols} rows={list.data?.results ?? []} rowKey={(x) => x.id} loading={list.loading} empty={{ title: t("ob.empty") }} />
      {openId && d && d.id === openId && (
        <section className="card" aria-label={d.ob_number}>
          <h2>{d.ob_number} · {cat(d.category)}</h2>
          <p><strong>{d.org_unit ? name(d.org_unit) : "—"}</strong> · {stamp(d.occurred_at)}{d.location ? ` · ${d.location}` : ""}</p>
          <p>{d.summary}</p>
          {d.details && <p style={{ whiteSpace: "pre-wrap" }}>{d.details}</p>}
          {d.reported_by && <p><strong>{t("ob.reportedBy")}:</strong> {d.reported_by}</p>}
          {d.detention && <p><strong>{t("ob.detention")}:</strong> {d.detention.register_no}</p>}
          <p className="muted">{t("ob.recordedBy")}: {d.recorded_by || "—"}</p>
          {d.voided_reason && <p><strong>{t("ob.voidedBecause")}:</strong> {d.voided_reason}</p>}
          <h3>{t("ob.followUps")}</h3>
          <ul>{d.follow_ups.map((f) => <li key={f.id}>{stamp(f.occurred_at)} · <strong>{t(`ob.follow.${f.kind}` as never)}</strong> — {f.text} <span className="muted">({f.by})</span></li>)}</ul>
          {canEdit && d.status === "recorded" && (<>
            <form className="card" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; void post(`/occurrence-book/${d.id}/follow-up/`, { version: d.version, ...clean(Object.fromEntries(new FormData(f).entries())) }).then((ok) => ok && f.reset()); }}>
              <Field label={t("ob.followKind")}><select name="kind" defaultValue="update">{FOLLOW_KINDS.map((k) => <option key={k} value={k}>{t(`ob.follow.${k}` as never)}</option>)}</select></Field>
              <Field label={t("ob.followText")}><input name="text" required maxLength={500} /></Field>
              <button type="submit">{t("ob.addFollow")}</button>
            </form>
            <button type="button" className="secondary" onClick={() => { const reason = window.prompt(t("ob.voidReason")); if (reason) void post(`/occurrence-book/${d.id}/void/`, { version: d.version, reason }); }}>{t("ob.void")}</button>
          </>)}
        </section>
      )}
    </>
  );
}
