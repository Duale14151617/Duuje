import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, Notice, PageHeader } from "../components/ui";
import { UnitPicker } from "../components/UnitPicker";
import { useI18n, type Key } from "../i18n";
import { formatDateTime, formatDay } from "../lib/format";

interface Named { code: string; name_en: string; name_so: string }
type Status = "fit" | "limited" | "unfit" | "under_review" | "unassessed";
interface Row {
  personnel: { id: string; full_name: string; service_number: string | null }; rank: Named;
  fitness_status: Status; review_due: string | null; overdue: boolean; restriction: string; assessed_at: string | null;
}
interface Entry {
  id: string; fitness_status: Exclude<Status, "unassessed">; review_due: string | null; restriction: string; details: string | null;
  corrects: string | null; superseded: boolean; recorded_at: string; recorded_by: string;
}
const TONE: Record<Status, string> = { fit: "ok", limited: "warn", unfit: "bad", under_review: "info", unassessed: "neutral" };
const ENTRY_STATUSES = ["fit", "limited", "unfit", "under_review"] as const;

/** Fitness for duty. Commanders see status, review date and duty restriction; only the medical officer sees the details. */
export function Fitness() {
  const { t, lang } = useI18n();
  const [unit, setUnit] = useState("");
  const [state, setState] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const data = useFetch<{ counts: Record<string, number>; results: Row[] }>(unit ? "/fitness/" : null, { org_unit: unit, state: state || undefined });
  const day = (s: string) => formatDay(s, lang);
  return (
    <>
      <PageHeader title={t("ft.title")} subtitle={t("ft.subtitle")} />
      <section className="card">
        <UnitPicker label={t("ft.unit")} value={unit} onChange={(id) => { setUnit(id); setOpen(null); }} />
        <ErrorNotice error={data.error} />
        {!unit && <p className="muted">{t("ft.pick")}</p>}
        {unit && data.data && (
          <>
            <div className="row">
              {(["fit", "limited", "unfit", "under_review", "unassessed"] as const).map((s) => (
                <Chip key={s} tone={TONE[s]}>{t(`ft.status.${s}` as Key)}: {data.data!.counts[s] ?? 0}</Chip>))}
              <Chip tone={data.data.counts.overdue ? "bad" : "neutral"}>{t("ft.overdueCount")}: {data.data.counts.overdue ?? 0}</Chip>
            </div>
            <Field label={t("ft.state")}>
              <select value={state} onChange={(e) => setState(e.target.value)}>
                <option value="">{t("common.all")}</option>
                {(["fit", "limited", "unfit", "under_review", "unassessed"] as const).map((s) => <option key={s} value={s}>{t(`ft.status.${s}` as Key)}</option>)}
                <option value="overdue">{t("ft.overdue")}</option>
              </select>
            </Field>
            {data.data.results.length === 0 && <p className="muted">{t("ft.noRows")}</p>}
            <ul className="list">
              {data.data.results.map((r) => (
                <li key={r.personnel.id} className="item">
                  <div className="row">
                    <b>{r.rank.code} {r.personnel.full_name}</b>
                    <Chip tone={TONE[r.fitness_status]}>{t(`ft.status.${r.fitness_status}` as Key)}</Chip>
                    {r.overdue && <Chip tone="bad">{t("ft.overdue")}</Chip>}
                  </div>
                  {r.restriction && <p>{t("ft.restriction")}: {r.restriction}</p>}
                  {r.review_due && <p className="muted">{t("ft.reviewDue")}: {day(r.review_due)}</p>}
                  <button type="button" className="secondary" onClick={() => setOpen(open === r.personnel.id ? null : r.personnel.id)}>
                    {open === r.personnel.id ? t("ft.hide") : t("ft.history")}
                  </button>
                  {open === r.personnel.id && <Person id={r.personnel.id} onChanged={() => data.reload()} />}
                </li>))}
            </ul>
          </>)}
      </section>
    </>
  );
}

function Person({ id, onChanged }: { id: string; onChanged: () => void }) {
  const { t, lang } = useI18n();
  const { can } = useAuth();
  const canManage = can("medical.manage");
  const h = useFetch<{ can_see_details: boolean; results: Entry[] }>("/fitness/history/", { personnel: id });
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [correcting, setCorrecting] = useState<string | null>(null);
  const when = (s: string) => formatDateTime(s, lang);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = Object.fromEntries(new FormData(form).entries());
    setError(null); setSaved(false);
    try {
      await api("/fitness/add/", { method: "POST", body: { personnel: id, ...f, review_due: f.review_due || undefined, corrects: correcting || undefined } });
      form.reset(); setCorrecting(null); setSaved(true); h.reload(); onChanged();
    } catch (err) { setError(err); }
  }

  return (
    <div className="mt-1">
      <ErrorNotice error={error ?? h.error} />
      {saved && <Notice>{t("ft.saved")}</Notice>}
      {h.data && !h.data.can_see_details && <p className="muted">{t("ft.detailsHidden")}</p>}
      {h.data && h.data.results.length === 0 && <p className="muted">{t("ft.noEntries")}</p>}
      <ul className="list">
        {(h.data?.results ?? []).map((e) => (
          <li key={e.id} className="item" style={e.superseded ? { opacity: 0.6 } : undefined}>
            <div className="row">
              <Chip tone={TONE[e.fitness_status]}>{t(`ft.status.${e.fitness_status}` as Key)}</Chip>
              {e.superseded && <Chip tone="neutral">{t("ft.superseded")}</Chip>}
              <span className="muted">{when(e.recorded_at)} · {t("ft.by", { by: e.recorded_by })}</span>
            </div>
            {e.restriction && <p>{t("ft.restriction")}: {e.restriction}</p>}
            {e.review_due && <p className="muted">{t("ft.reviewDue")}: {e.review_due}</p>}
            {e.details && <p>{t("ft.details")}: {e.details}</p>}
            {canManage && !e.superseded && <button type="button" className="secondary" onClick={() => setCorrecting(e.id)}>{t("ft.correct")}</button>}
          </li>))}
      </ul>
      {canManage && (
        <form onSubmit={(e) => void submit(e)}>
          <h4>{correcting ? t("ft.correcting") : t("ft.add")}</h4>
          <Field label={t("ft.status")}>
            <select name="fitness_status" required defaultValue="">
              <option value="" />
              {ENTRY_STATUSES.map((s) => <option key={s} value={s}>{t(`ft.status.${s}` as Key)}</option>)}
            </select>
          </Field>
          <Field label={t("ft.reviewDue")}><input type="date" name="review_due" /></Field>
          <Field label={t("ft.restriction")}><input name="restriction" maxLength={300} /></Field>
          <p className="muted">{t("ft.restrictionHint")}</p>
          {h.data?.can_see_details && <Field label={t("ft.details")}><textarea name="details" maxLength={4000} rows={3} /></Field>}
          <button type="submit">{t("ft.save")}</button>
          {correcting && <button type="button" className="secondary" onClick={() => setCorrecting(null)}>{t("common.cancel")}</button>}
        </form>)}
    </div>
  );
}
