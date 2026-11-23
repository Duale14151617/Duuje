import { Link } from "react-router-dom";
import type { HistoryEntry, Page, Person, TrainingRec } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useI18n, type Key } from "../i18n";
import { yearsSince } from "../lib/time";
import { DataTable, type Column } from "./DataTable";
import { statusTone } from "./status";
import { Chip, ErrorNotice, EmptyState, formatDate } from "./ui";

const isoDaysAgo = (n: number) => new Date(Date.now() - n * 864e5).toISOString().slice(0, 10);

/** Rank and unit changes, or status changes, or everything, as one dated timeline. Same data and wording as the old flat history list. */
export function HistoryTimeline({ entries, fields }: { entries: HistoryEntry[]; fields?: HistoryEntry["field"][] }) {
  const { t, lang, tr } = useI18n();
  const shown = fields ? entries.filter((h) => fields.includes(h.field)) : entries;
  const label = (h: HistoryEntry, value: string) => (h.field === "status" ? tr(`pstatus.${value}`) ?? value : value);
  if (shown.length === 0) return <EmptyState icon="clock" title={t("pf.noHistory")} />;
  return (
    <ul className="timeline">
      {shown.map((h) => (
        <li key={h.id}>
          <b>{t(`hist.${h.field}` as Key)}</b>{" "}
          {h.old_label ? `${label(h, h.old_label)} → ${label(h, h.new_label)}` : label(h, h.new_label)}
          <div className="muted">
            {h.effective_date} · {h.recorded_by_username || "-"} · {formatDate(h.recorded_at, lang)}
            {h.reason ? ` · ${h.reason}` : ""}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Current service facts plus the rank and posting timeline. Enlistment date comes from the identity profile, which only managers may read. */
export function ServiceRecordTab({ person, history, canManage }: { person: Person; history: HistoryEntry[]; canManage: boolean }) {
  const { t, name } = useI18n();
  const profile = useFetch<{ enlistment_date: string | null }>(canManage ? `/personnel/${person.id}/profile/` : null);
  const years = yearsSince(profile.data?.enlistment_date);
  return (
    <div className="pf-grid">
      <section className="card">
        <h2>{t("pf.serviceSummary")}</h2>
        <dl className="kv">
          <div><dt>{t("pers.serviceNumber")}</dt><dd>{person.service_number ?? "-"}</dd></div>
          <div><dt>{t("pers.branch")}</dt><dd>{name(person.branch)}</dd></div>
          <div><dt>{t("pers.rank")}</dt><dd>{person.rank.code} {name(person.rank)}</dd></div>
          <div><dt>{t("pers.unit")}</dt><dd>{name(person.org_unit)}</dd></div>
          <div><dt>{t("pers.status")}</dt><dd><Chip tone={statusTone(person.status)}>{t(`pstatus.${person.status}` as Key)}</Chip></dd></div>
          {canManage && <div><dt>{t("pf.enlistment")}</dt><dd>{profile.data?.enlistment_date || "-"}</dd></div>}
          {canManage && <div><dt>{t("pf.yearsOfService")}</dt><dd>{years === null ? "-" : t("pf.years", { n: years })}</dd></div>}
        </dl>
        <ErrorNotice error={profile.error} />
      </section>
      <section className="card">
        <h2>{t("pf.rankPostings")}</h2>
        <HistoryTimeline entries={history} fields={["rank", "org_unit"]} />
      </section>
    </div>
  );
}

interface AttRec { id: string; report_date: string; status: string; reason: string | null; note: string; reported_by: string; amended: boolean }
interface Reason { code: string; name_en: string; name_so: string }

/** The person's own attendance for the last 90 days. Read through the attendance module, so its permission and unit scope apply. */
export function AttendanceTab({ person }: { person: Person }) {
  const { t, name } = useI18n();
  const recs = useFetch<{ results: AttRec[] }>("/attendance/records/", { org_unit: person.org_unit.id, personnel: person.id, from: isoDaysAgo(90) });
  const reasons = useFetch<{ results: Reason[] }>("/attendance/reasons/");
  const reasonName = (code: string | null) => {
    const r = reasons.data?.results.find((x) => x.code === code);
    return r ? name(r) : code ?? "-";
  };
  const columns: Column<AttRec>[] = [
    { id: "date", header: t("att.date"), width: 130, locked: true, sort: (r) => r.report_date, cell: (r) => r.report_date },
    { id: "status", header: t("pers.status"), width: 140, sort: (r) => r.status,
      cell: (r) => <Chip tone={r.status === "present" ? "ok" : r.status === "absent" ? "bad" : "warn"}>{t(`att.status.${r.status}` as Key)}</Chip> },
    { id: "reason", header: t("att.reason"), width: 200, cell: (r) => (r.reason ? reasonName(r.reason) : "-") },
    { id: "note", header: t("att.note"), width: 240, cell: (r) => r.note || "-" },
    { id: "by", header: t("att.recordedBy"), width: 160, hidden: true, cell: (r) => <>{r.reported_by || "-"}{r.amended ? <span className="cell-sub">{t("att.amended")}</span> : null}</> },
  ];
  return (
    <section>
      <h2>{t("pf.attendanceRecent")}</h2>
      <ErrorNotice error={recs.error} />
      <DataTable id="person-attendance" caption={t("pf.attendanceRecent")} columns={columns} rows={recs.data?.results} rowKey={(r) => r.id}
                 loading={recs.loading} initialSort={{ id: "date", dir: "desc" }} clientPageSize={10}
                 empty={{ icon: "calendar", title: t("pf.noAttendance") }} />
    </section>
  );
}

/** The person's training records, newest first; each opens the existing training record page. */
export function TrainingTab({ person }: { person: Person }) {
  const { t, name } = useI18n();
  const recs = useFetch<Page<TrainingRec>>("/training/records/", { personnel: person.id, page_size: 100 });
  const columns: Column<TrainingRec>[] = [
    { id: "course", header: t("pf.course"), width: 240, locked: true, sort: (r) => name(r.course),
      cell: (r) => <Link to={`/training/records/${r.id}`}>{name(r.course)}</Link> },
    { id: "status", header: t("pers.status"), width: 140, sort: (r) => r.status, cell: (r) => <Chip tone={statusTone(r.status)}>{t(`tstatus.${r.status}` as Key)}</Chip> },
    { id: "start", header: t("pf.start"), width: 130, sort: (r) => r.start_date, cell: (r) => r.start_date },
    { id: "end", header: t("pf.end"), width: 130, sort: (r) => r.end_date, cell: (r) => r.end_date ?? "-" },
    { id: "done", header: t("pf.completedOn"), width: 140, sort: (r) => r.completed_on, cell: (r) => r.completed_on ?? "-" },
  ];
  return (
    <section>
      <h2>{t("pf.trainingRecords")}</h2>
      <ErrorNotice error={recs.error} />
      <DataTable id="person-training" caption={t("pf.trainingRecords")} columns={columns} rows={recs.data?.results} rowKey={(r) => r.id}
                 loading={recs.loading} initialSort={{ id: "start", dir: "desc" }} clientPageSize={10}
                 empty={{ icon: "cap", title: t("pf.noTraining") }} />
    </section>
  );
}
