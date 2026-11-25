import { useState } from "react";
import { api } from "../api/client";
import type { Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Field, PageHeader } from "../components/ui";
import { useI18n } from "../i18n";

interface UnitB { id: string; code: string; name_en: string; name_so: string }
interface Inc {
  id: string; record: { id: string; register_no: string }; org_unit: UnitB | null; kind: "death" | "injury" | "use_of_force"; occurred_at: string; place: string;
  description: string; people_involved: string; medical_attended: boolean; medical_note: string; reported_by: string; reviewed: boolean;
  reviewed_at: string | null; reviewed_by: string; review_note: string; version: number;
}
const stamp = (s: string | null) => (s ? s.slice(0, 16).replace("T", " ") : "—");

/** Deaths, injuries and use of force in custody. Reports go to every commander whose scope covers the station; a regional authority reviews them. */
export function CustodyIncidents() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const canReview = can("detention.incident_review");
  const [reviewed, setReviewed] = useState("0");
  const [kind, setKind] = useState("");
  const [note, setNote] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const list = useFetch<Page<Inc>>("/custody-incidents/", { reviewed: reviewed || undefined, kind: kind || undefined, page_size: 100 });

  async function review(i: Inc) {
    setError(null);
    try { await api(`/custody-incidents/${i.id}/review/`, { method: "POST", body: { version: i.version, note: note[i.id] ?? "" } }); list.reload(); } catch (e) { setError(e); }
  }
  return (
    <>
      <PageHeader title={t("inc.title")} subtitle={t("inc.subtitle")} />
      <div className="row">
        <Field label={t("det.state")}>
          <select value={reviewed} onChange={(e) => setReviewed(e.target.value)}>
            <option value="">{t("common.all")}</option><option value="0">{t("inc.awaiting")}</option><option value="1">{t("inc.reviewed")}</option>
          </select>
        </Field>
        <Field label={t("inc.kind")}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">{t("common.all")}</option>{["death", "injury", "use_of_force"].map((k) => <option key={k} value={k}>{t(`inc.kind.${k}` as never)}</option>)}
          </select>
        </Field>
      </div>
      {error != null && <ErrorNotice error={error} />}
      {(list.data?.results.length ?? 0) === 0 && !list.loading && <p>{t("inc.none")}</p>}
      {list.data?.results.map((i) => (
        <section key={i.id} className="card" aria-label={i.record.register_no}>
          <h3>{t(`inc.kind.${i.kind}` as never)} · {i.record.register_no} {i.reviewed ? <Chip tone="approved">{t("inc.reviewed")}</Chip> : <Chip tone="bad">{t("inc.awaiting")}</Chip>}</h3>
          <p>{i.org_unit ? name(i.org_unit) : "—"} · {stamp(i.occurred_at)}{i.place ? ` · ${i.place}` : ""} · {t("inc.reportedBy")} {i.reported_by}</p>
          <p>{i.description}</p>
          {i.people_involved && <p><strong>{t("inc.people")}:</strong> {i.people_involved}</p>}
          <p><strong>{t("inc.medical")}:</strong> {i.medical_attended ? t("users.f.yes") : t("users.f.no")}{i.medical_note ? ` · ${i.medical_note}` : ""}</p>
          {i.reviewed
            ? <p><strong>{t("inc.review")}:</strong> {i.review_note} <span className="muted">({i.reviewed_by}, {stamp(i.reviewed_at)})</span></p>
            : canReview && (
              <form onSubmit={(e) => { e.preventDefault(); void review(i); }}>
                <Field label={t("inc.reviewNote")}><input value={note[i.id] ?? ""} onChange={(e) => setNote({ ...note, [i.id]: e.target.value })} required maxLength={500} /></Field>
                <button type="submit">{t("inc.markReviewed")}</button>
              </form>)}
        </section>))}
    </>
  );
}
