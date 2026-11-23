import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { AuditEvent, Dashboard as Data, Page, SubmissionRow, UnitTaskOut } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import { timeAgo } from "../lib/time";
import { Icon, type IconName } from "./Icon";
import { Chip } from "./ui";
import { statusTone } from "./status";

function Head({ icon, title, id, to, link, tone = "" }: { icon: IconName; title: string; id: string; to?: string; link?: string; tone?: string }) {
  return (
    <header><span className={`ico ${tone}`}><Icon name={icon} size={18} /></span><h2 id={id}>{title}</h2>{to && link ? <Link className="panel-link" to={to}>{link}</Link> : null}</header>
  );
}

/** Reports waiting for this person's review, oldest-first as the server returns them; each opens the existing report page. */
export function ReviewQueuePanel({ count }: { count: number }) {
  const { t, name } = useI18n();
  const list = useFetch<Page<SubmissionRow>>(count > 0 ? "/reports/submissions/" : null, { awaiting_review: 1, page_size: 5 });
  const rows = list.data?.results ?? [];
  return (
    <section className="panel" aria-labelledby="dash-review">
      <Head icon="file" tone={count > 0 ? "warn" : "ok"} id="dash-review" title={t("dash.reviewQueue")} to="/reports" link={t("dash.viewAll")} />
      <p className="panel-figure"><b className={count > 0 ? "warn" : "zero"}>{count.toLocaleString()}</b></p>
      {count === 0 ? <p className="muted" role="status">{t("dash.reviewNone")}</p> : rows.length === 0 ? <div className="skeleton-line" role="status" aria-label={t("common.loading")} /> : (
        <ul className="mini-list">
          {rows.map((s) => (
            <li key={s.id}><Link to={`/reports/${s.id}`}><b>{s.title || name(s.report_type)}</b></Link>
              <span className="muted">{name(s.org_unit)} · {s.period_start}</span></li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Open and in-progress unit tasks, overdue first. The counts are over the tasks the server returns for this user. */
export function TasksPanel() {
  const { t } = useI18n();
  const list = useFetch<{ results: UnitTaskOut[] }>("/operations/tasks/");
  if (list.error) return null;
  const open = (list.data?.results ?? []).filter((x) => x.status === "open" || x.status === "in_progress");
  const overdue = open.filter((x) => x.overdue).length;
  const next = [...open].sort((a, b) => Number(b.overdue) - Number(a.overdue) || (a.due_on ?? "9999").localeCompare(b.due_on ?? "9999")).slice(0, 4);
  return (
    <section className="panel" aria-labelledby="dash-tasks">
      <Head icon="check" tone={overdue > 0 ? "bad" : open.length > 0 ? "warn" : "ok"} id="dash-tasks" title={t("dash.tasksOutstanding")} to="/tasks" link={t("dash.viewAll")} />
      <p className="panel-figure"><b className={open.length > 0 ? "" : "zero"}>{open.length.toLocaleString()}</b>
        {overdue > 0 && <Chip tone="bad">{t("dash.tasksOverdue", { n: overdue })}</Chip>}</p>
      {list.loading && !list.data ? <div className="skeleton-line" role="status" aria-label={t("common.loading")} /> : next.length === 0 ? <p className="muted" role="status">{t("dash.tasksNone")}</p> : (
        <ul className="mini-list">
          {next.map((x) => (
            <li key={x.id}><Link to="/tasks"><b>{x.title}</b></Link>
              <span className="muted">{x.org_unit_name}{x.due_on ? ` · ${t("dash.tasksDue", { date: x.due_on })}` : ""}</span></li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** How much of the enrolled workload has started. Figures come from the dashboard payload. */
export function TrainingPanel({ training }: { training: NonNullable<Data["training"]> }) {
  const { t } = useI18n();
  const all = training.in_progress + training.enrolled;
  const share = all > 0 ? Math.round((training.in_progress / all) * 100) : 0;
  return (
    <section className="panel" aria-labelledby="dash-training">
      <Head icon="cap" id="dash-training" title={t("dash.trainingProgress")} to="/training" link={t("dash.viewAll")} />
      {all === 0 ? <p className="muted" role="status">{t("dash.trainingNone")}</p> : (
        <>
          <p className="panel-figure"><b>{training.in_progress.toLocaleString()}</b><span className="muted">{t("dash.inProgress")}</span></p>
          <div className="meter" role="img" aria-label={t("dash.trainingShare", { n: share })}><span style={{ width: `${share}%` }} /></div>
          <div className="prow"><span>{t("dash.inProgress")}</span><b>{training.in_progress.toLocaleString()}</b></div>
          <div className="prow"><span>{t("dash.enrolled")}</span><b>{training.enrolled.toLocaleString()}</b></div>
          <p className="muted">{t("dash.trainingShare", { n: share })}</p>
        </>
      )}
    </section>
  );
}

function Tile({ tone, icon, label, value, note, to, go }: { tone: "ok" | "warn" | "bad"; icon: IconName; label: string; value: string; note: string; to: string; go: string }) {
  return (
    <Link to={to} className={`health-tile ${tone}`} aria-label={`${label}: ${value}. ${note}. ${go}`}>
      <span className="ico"><Icon name={icon} size={18} /></span>
      <span className="health-label">{label}</span>
      <span className="health-value">{value}</span>
      <span className="health-note">{note}</span>
    </Link>
  );
}

/** MFA compliance, account status, denied requests and failed sign-ins side by side; red means someone should act now. */
export function SecurityPanel({ accounts, audit }: { accounts?: Data["accounts"]; audit?: Data["audit"] }) {
  const { t } = useI18n();
  const { can } = useAuth();
  if (!accounts && !audit) return null;
  const tiles: ReactNode[] = [];
  let worst = false;
  if (accounts) {
    const gap = accounts.privileged_without_mfa;
    if (gap > 0) worst = true;
    tiles.push(<Tile key="mfa" tone={gap > 0 ? "bad" : "ok"} icon="lock" label={t("dash.mfaCompliance")} value={gap > 0 ? gap.toLocaleString() : t("dash.healthy")}
      note={gap > 0 ? t("dash.mfaGap", { n: gap }) : t("dash.mfaOk")} to="/users" go={t("dash.openUsers")} />);
    tiles.push(<Tile key="acc" tone="ok" icon="users" label={t("dash.accountStatus")} value={accounts.active.toLocaleString()}
      note={t("dash.accountsSplit", { active: accounts.active.toLocaleString(), disabled: accounts.disabled.toLocaleString() })} to="/users" go={t("dash.openUsers")} />);
  }
  if (audit) {
    if (audit.failed_logins_24h > 0) worst = true;
    const filterTo = (outcome: string, action?: string) => `/audit?outcome=${outcome}${action ? `&action=${encodeURIComponent(action)}` : ""}`;
    tiles.push(<Tile key="den" tone={audit.denied_24h > 0 ? "warn" : "ok"} icon="alert" label={t("dash.deniedRequests")} value={audit.denied_24h.toLocaleString()}
      note={audit.denied_24h > 0 ? t("dash.needsAttention") : t("dash.healthy")} to={filterTo("denied")} go={t("dash.openAuditLog")} />);
    tiles.push(<Tile key="fail" tone={audit.failed_logins_24h > 0 ? "bad" : "ok"} icon="activity" label={t("dash.failedSignins")} value={audit.failed_logins_24h.toLocaleString()}
      note={audit.failed_logins_24h > 0 ? t("dash.needsAttention") : t("dash.healthy")} to={filterTo("failure", "auth.login")} go={t("dash.openAuditLog")} />);
  }
  return (
    <section className={`panel health${worst ? " has-bad" : ""}`} aria-labelledby="dash-health">
      <header><span className={`ico ${worst ? "bad" : "ok"}`}><Icon name={worst ? "alert" : "check"} size={18} /></span><h2 id="dash-health">{t("dash.sinceYesterday")}</h2>
        {can("audit.view") && <Link className="panel-link" to="/audit">{t("dash.openAuditLog")}</Link>}</header>
      <div className="health-grid">{tiles}</div>
    </section>
  );
}

/** The most recent failed or denied audit events, for people who may read the audit log. */
export function ExceptionsPanel() {
  const { t, lang } = useI18n();
  const failed = useFetch<Page<AuditEvent>>("/audit-events/", { outcome: "failure", page_size: 5 });
  const denied = useFetch<Page<AuditEvent>>("/audit-events/", { outcome: "denied", page_size: 5 });
  if (failed.error && denied.error) return null;
  const rows = [...(failed.data?.results ?? []), ...(denied.data?.results ?? [])]
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)).slice(0, 6);
  const loading = (failed.loading && !failed.data) || (denied.loading && !denied.data);
  return (
    <section className="panel chart-panel" aria-labelledby="dash-exc">
      <Head icon="alert" tone={rows.length > 0 ? "warn" : "ok"} id="dash-exc" title={t("dash.exceptions")} to="/audit?outcome=failure" link={t("dash.viewAll")} />
      {loading ? <div className="skeleton-line" role="status" aria-label={t("common.loading")} /> : rows.length === 0 ? <p className="muted" role="status">{t("dash.exceptionsNone")}</p> : (
        <ul className="activity">
          {rows.map((e) => (
            <li key={e.id}>
              <span className="ico"><Icon name="alert" size={16} /></span>
              <div className="activity-main"><b>{e.action}</b><span className="muted">{[e.actor_username || "-", e.entity_type].filter(Boolean).join(" · ")}</span></div>
              <Chip tone={statusTone(e.outcome)}>{e.outcome}</Chip>
              <time className="activity-time" dateTime={e.occurred_at}>{timeAgo(e.occurred_at, lang)}</time>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
