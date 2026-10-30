import { useState } from "react";
import { Link } from "react-router-dom";
import type { AuditEvent, Dashboard as Data, DayActivity, NotificationItem, Page } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Icon, type IconName } from "../components/Icon";
import { Chip, ErrorNotice } from "../components/ui";
import { statusTone } from "../components/status";
import { formatLongDate, greetingKey, timeAgo } from "../lib/time";
import { useI18n } from "../i18n";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { ActivityChart, ChartPanel, RangeSwitch, RegionChart } from "../components/DashboardCharts";

type Row = [label: string, value: number, tone?: string];

/** Share of a whole (0 to 1) as a ring; decorative, the figure itself is the text beside it. */
function Ring({ share }: { share: number }) {
  const r = 17, c = 2 * Math.PI * r;
  return (
    <svg className="ring" viewBox="0 0 44 44" aria-hidden="true">
      <circle className="ring-track" cx="22" cy="22" r={r} />
      <circle className="ring-arc" cx="22" cy="22" r={r} strokeDasharray={`${c * Math.min(1, Math.max(0, share))} ${c}`} transform="rotate(-90 22 22)" />
    </svg>
  );
}

function Kpi({ icon, label, value, to, suffix = "", tone = "", ring, sub }:
  { icon: IconName; label: string; value: number; to: string; suffix?: string; tone?: string; ring?: number; sub?: string }) {
  return (
    <Link to={to} className={`kpi ${tone}${value === 0 && !tone ? " zero" : ""}`}>
      {ring !== undefined ? <Ring share={ring} /> : <span className={`ico ${tone}`}><Icon name={icon} /></span>}
      <span className="num">{value.toLocaleString()}{suffix}</span>
      <span className="lbl">{label}</span>
      {sub ? <span className="sub">{sub}</span> : null}
    </Link>
  );
}

interface AttendanceDay { serving: number; present: number; absent: number; on_leave: number; recorded: number; not_recorded: number }

/** Donut of today's attendance for the user's own unit. Segments are lengths of one circle; the legend carries the exact figures. */
function Donut({ parts, centre, caption }: { parts: { key: string; value: number; tone: string }[]; centre: string; caption: string }) {
  const r = 38, c = 2 * Math.PI * r;
  const total = parts.reduce((n, x) => n + x.value, 0);
  let offset = 0;
  return (
    <svg className="donut" viewBox="0 0 100 100" aria-hidden="true">
      <circle className="donut-track" cx="50" cy="50" r={r} />
      {total > 0 && parts.filter((x) => x.value > 0).map((x) => {
        const len = (x.value / total) * c;
        const el = <circle key={x.key} className={`donut-seg ${x.tone}`} cx="50" cy="50" r={r} strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} transform="rotate(-90 50 50)" />;
        offset += len;
        return el;
      })}
      <text className="donut-num" x="50" y="53">{centre}</text>
      <text className="donut-cap" x="50" y="67">{caption}</text>
    </svg>
  );
}

function AttendanceCard({ unitId, unitName }: { unitId: string; unitName: string }) {
  const { t } = useI18n();
  const today = new Date().toISOString().slice(0, 10);
  const a = useFetch<AttendanceDay>("/attendance/summary/", { org_unit: unitId, period: "day", date: today });
  if (a.error || !a.data) return a.loading ? <div className="panel skeleton tall" role="status" aria-busy="true" aria-label={t("common.loading")} /> : null;
  const d = a.data;
  const rate = d.serving > 0 && d.recorded > 0 ? Math.round((d.present / d.serving) * 100) : null;
  return (
    <section className="panel" aria-labelledby="dash-att">
      <header><span className="ico"><Icon name="calendar" size={18} /></span><h2 id="dash-att">{t("dash.attendanceToday")}</h2><Link className="panel-link" to="/attendance">{t("dash.review")}</Link></header>
      <p className="muted">{unitName}</p>
      {d.recorded === 0 ? <p className="muted">{t("dash.attendanceNone")}</p> : (
        <div className="donut-wrap">
          <Donut parts={[{ key: "p", value: d.present, tone: "ok" }, { key: "a", value: d.absent, tone: "bad" }, { key: "l", value: d.on_leave, tone: "warn" }, { key: "n", value: d.not_recorded, tone: "mute" }]}
                 centre={rate === null ? "-" : `${rate}%`} caption={t("att.status.present")} />
          <ul className="legend-list">
            <li><span className="dot ok" />{t("att.status.present")}<b>{d.present.toLocaleString()}</b></li>
            <li><span className="dot bad" />{t("att.status.absent")}<b>{d.absent.toLocaleString()}</b></li>
            <li><span className="dot warn" />{t("att.status.on_leave")}<b>{d.on_leave.toLocaleString()}</b></li>
            <li><span className="dot mute" />{t("att.notRecorded")}<b>{d.not_recorded.toLocaleString()}</b></li>
          </ul>
        </div>
      )}
    </section>
  );
}

/** Shortcuts to jobs the signed-in user is already allowed to do; each opens the existing page. */
function QuickActions() {
  const { t } = useI18n();
  const { can } = useAuth();
  const items: { to: string; icon: IconName; label: string; show: boolean }[] = [
    { to: "/personnel/new", icon: "plus", label: t("pers.add"), show: can("personnel.manage") },
    { to: "/attendance", icon: "calendar", label: t("dash.qaAttendance"), show: can("attendance.record") },
    { to: "/reports/new", icon: "file", label: t("dash.qaReport"), show: can("reports.submit") },
    { to: "/personnel", icon: "users", label: t("nav.personnel"), show: can("personnel.view") || can("personnel.view_team") },
    { to: "/logistics", icon: "box", label: t("nav.logistics"), show: ["logistics.view", "logistics.restricted", "logistics.manage"].some(can) },
  ].filter((x) => x.show);
  if (items.length === 0) return null;
  return (
    <section className="panel" aria-labelledby="dash-quick">
      <header><span className="ico"><Icon name="zap" size={18} /></span><h2 id="dash-quick">{t("dash.quick")}</h2></header>
      <div className="quick">
        {items.map((x) => <Link key={x.to} to={x.to} className="quick-item"><span className="ico"><Icon name={x.icon} size={16} /></span>{x.label}</Link>)}
      </div>
    </section>
  );
}

/** Latest audit events for people who may read the audit log, otherwise the person's own notifications. */
function RecentActivity() {
  const { t, tr, lang } = useI18n();
  const { can } = useAuth();
  const audit = can("audit.view");
  const events = useFetch<Page<AuditEvent>>(audit ? "/audit-events/" : null, { page_size: 6 });
  const notes = useFetch<Page<NotificationItem>>(audit ? null : "/notifications/", { page_size: 6 });
  const rows: { id: string; icon: IconName; title: string; sub: string; at: string; chip?: { tone: string; text: string } }[] = audit
    ? (events.data?.results ?? []).map((e) => ({ id: e.id, icon: "activity", title: e.action, sub: [e.actor_username || "-", e.entity_type].filter(Boolean).join(" · "), at: e.occurred_at,
        chip: { tone: statusTone(e.outcome), text: e.outcome } }))
    : (notes.data?.results ?? []).map((n) => ({ id: n.id, icon: "bell", title: tr(`nkind.${n.kind}`) ?? n.kind, sub: n.submission?.title ?? t("note.noAccess"), at: n.created_at }));
  const src = audit ? events : notes;
  if (src.error) return null;
  return (
    <section className="panel" aria-labelledby="dash-recent">
      <header><span className="ico"><Icon name="clock" size={18} /></span><h2 id="dash-recent">{t("dash.recent")}</h2>
        <Link className="panel-link" to={audit ? "/audit" : "/notifications"}>{t("dash.viewAll")}</Link></header>
      {src.loading && !src.data ? <div className="skeleton-line" role="status" aria-label={t("common.loading")} /> : rows.length === 0 ? <p className="muted">{t("dash.recentNone")}</p> : (
        <ul className="activity">
          {rows.map((r) => (
            <li key={r.id}>
              <span className="ico"><Icon name={r.icon} size={16} /></span>
              <div className="activity-main"><b>{r.title}</b><span className="muted">{r.sub}</span></div>
              {r.chip ? <Chip tone={r.chip.tone}>{r.chip.text}</Chip> : null}
              <time className="activity-time" dateTime={r.at}>{timeAgo(r.at, lang)}</time>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Panel({ icon, title, rows, meter }: { icon: IconName; title: string; rows: Row[]; meter?: number }) {
  return (
    <section className="panel">
      <header><span className="ico"><Icon name={icon} size={18} /></span><h2>{title}</h2></header>
      {meter !== undefined && <div className="meter" aria-hidden="true"><span style={{ width: `${Math.round(meter * 100)}%` }} /></div>}
      {rows.map(([label, value, tone]) => (
        <div className="prow" key={label}><span>{label}</span><b className={tone || (value === 0 ? "zero" : "")}>{value.toLocaleString()}</b></div>
      ))}
    </section>
  );
}

/** Placeholder cards shown while the dashboard loads, so the page does not jump when data arrives. */
function Skeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-busy="true" aria-label={label}>
      <div className="kpis">{[0, 1, 2, 3].map((i) => <div key={i} className="kpi skeleton" />)}</div>
      <div className="grid">{[0, 1, 2].map((i) => <div key={i} className="panel skeleton tall" />)}</div>
    </div>
  );
}

export function Dashboard() {
  const { t, name, lang } = useI18n();
  const { me, can } = useAuth();
  const { data: n, error, loading } = useFetch<Data>("/dashboard/");
  const [range, setRange] = useState<7 | 30>(7);
  const longer = useFetch<{ daily: DayActivity[] }>(range === 30 && n?.audit ? "/dashboard/activity/" : null, { days: 30 });
  // the user's first assignment gives the unit for unit-level figures (attendance today, vehicles)
  const home = me?.assignments[0]?.org_unit;
  const vehicles = useFetch<{ combined: { total: number; unavailable: number } }>(can("vehicles.view") && home ? "/vehicles/summary/" : null, { org_unit: home?.id });
  const warn = (k: Parameters<typeof t>[0], v: number, tone = v > 0 ? "warn" : ""): Row => [t(k), v, tone];
  const plain = (k: Parameters<typeof t>[0], v: number): Row => [t(k), v];
  const first = me?.full_name.split(" ")[0];
  const now = new Date();

  let body = null;
  let pdfSections: { title: string; rows: [string, string][] }[] = [];
  if (n) {
    // Things that wait for a decision by this person, then things that merely deserve a look.
    const approvals = [
      { to: "/reports", label: t("dash.awaiting"), n: n.reports?.awaiting_review ?? 0, bad: false },
      { to: "/ranks", label: t("dash.draftRanks"), n: can("ranks.approve") ? n.ranks?.draft ?? 0 : 0, bad: false },
    ].filter((x) => x.n > 0);
    const attention = [
      { to: "/logistics", label: t("dash.lowStock"), n: n.logistics?.low_stock ?? 0, bad: false },
      { to: "/logistics", label: t("dash.assetsAttention"), n: n.logistics?.assets_attention ?? 0, bad: false },
      { to: "/users", label: t("dash.noMfa"), n: n.accounts?.privileged_without_mfa ?? 0, bad: true },
      { to: "/audit", label: t("dash.failedLogins"), n: n.audit?.failed_logins_24h ?? 0, bad: true },
      { to: "/audit", label: t("dash.denied"), n: n.audit?.denied_24h ?? 0, bad: true },
    ].filter((x) => x.n > 0);
    const activeShare = n.personnel && n.personnel.total > 0 ? n.personnel.active / n.personnel.total : undefined;

    // Panels add detail beyond the headline cards, so the same number is not shown twice.
    // `pdf` keeps the full figures for the exported PDF.
    const panels: { icon: IconName; title: string; rows: Row[]; meter?: number; pdf?: Row[] }[] = [];
    if (n.personnel) {
      const full: Row[] = [plain("dash.total", n.personnel.total), plain("dash.activePersonnel", n.personnel.active)];
      panels.push({ icon: "users", title: t("dash.personnelTitle"), meter: activeShare,
        rows: [plain("dash.inactive", n.personnel.total - n.personnel.active)], pdf: full });
    }
    if (n.scope) {
      const full: Row[] = [plain("dash.units", n.scope.units_in_scope), plain("dash.regions", n.scope.regions_in_scope), plain("dash.branchCommands", n.scope.branch_commands_in_scope)];
      panels.push({ icon: "map", title: t("dash.scopeTitle"), rows: full.slice(1), pdf: full });
    }
    if (n.ranks) panels.push({ icon: "award", title: t("dash.ranksTitle"),
      rows: [warn("dash.draft", n.ranks.draft), plain("dash.approved", n.ranks.approved)] });
    if (n.reports) {
      const full: Row[] = [plain("dash.myOpen", n.reports.my_open), ...(n.reports.awaiting_review !== undefined ? [warn("dash.awaiting", n.reports.awaiting_review)] : [])];
      panels.push({ icon: "file", title: t("dash.reportsTitle"), rows: full });
    }
    if (n.logistics) panels.push({ icon: "box", title: t("dash.logisticsTitle"),
      rows: [warn("dash.lowStock", n.logistics.low_stock), warn("dash.assetsAttention", n.logistics.assets_attention)] });
    if (n.training) panels.push({ icon: "cap", title: t("dash.trainingTitle"),
      rows: [plain("dash.inProgress", n.training.in_progress), plain("dash.enrolled", n.training.enrolled)] });
    if (n.accounts) panels.push({ icon: "lock", title: t("dash.accountsTitle"),
      rows: [plain("dash.activeUsers", n.accounts.active), plain("dash.disabledUsers", n.accounts.disabled),
        warn("dash.noMfa", n.accounts.privileged_without_mfa, n.accounts.privileged_without_mfa > 0 ? "bad" : "")] });
    if (n.audit) panels.push({ icon: "activity", title: t("dash.auditTitle"),
      rows: [plain("dash.events", n.audit.events_24h), warn("dash.failedLogins", n.audit.failed_logins_24h), warn("dash.denied", n.audit.denied_24h)] });
    const regionRows = n.personnel?.by_region ?? [];
    const daily = n.audit?.daily;
    const series = range === 7 ? daily : longer.data?.daily;
    pdfSections = panels.map((p) => ({ title: p.title, rows: (p.pdf ?? p.rows).map(([l, v]) => [l, v.toLocaleString()] as [string, string]) }));
    if (regionRows.length > 1) pdfSections.push({ title: t("dash.byRegion"),
      rows: regionRows.map((r) => [r.code === null ? t("level.headquarters") : name(r), r.total.toLocaleString()] as [string, string]) });

    // Headline cards, each a shortcut to its page. Up to six that apply to this role are shown.
    const openReports = n.reports?.awaiting_review ?? n.reports?.my_open;
    const veh = vehicles.data?.combined;
    const kpis = [
      n.personnel && <Kpi key="p" to="/personnel" icon="users" label={t("dash.personnelTitle")} value={n.personnel.total} sub={t("dash.activeSub", { n: n.personnel.active.toLocaleString() })} />,
      activeShare !== undefined && <Kpi key="a" to="/personnel" icon="check" label={t("dash.activeShare")} value={Math.round(activeShare * 100)} suffix="%" ring={activeShare} />,
      n.scope && <Kpi key="u" to="/organization" icon="layers" label={t("dash.units")} value={n.scope.units_in_scope} />,
      veh && <Kpi key="v" to="/vehicles" icon="truck" label={t("dash.vehicles")} value={veh.total} sub={t("dash.vehiclesSub", { n: veh.unavailable })} tone={veh.unavailable > 0 ? "warn" : ""} />,
      openReports !== undefined && <Kpi key="r" to="/reports" icon="file" label={n.reports?.awaiting_review !== undefined ? t("dash.awaiting") : t("dash.myOpen")}
        value={openReports} tone={n.reports?.awaiting_review ? "warn" : ""} />,
      n.logistics && <Kpi key="l" to="/logistics" icon="box" label={t("dash.lowStock")} value={n.logistics.low_stock} tone={n.logistics.low_stock > 0 ? "warn" : ""} />,
      n.training && <Kpi key="t" to="/training" icon="cap" label={t("dash.inProgress")} value={n.training.in_progress} />,
      n.accounts && <Kpi key="c" to="/users" icon="lock" label={t("dash.activeUsers")} value={n.accounts.active} />,
    ].filter(Boolean).slice(0, 6);

    const row = (x: { to: string; label: string; n: number; bad: boolean }) => (
      <Link key={x.label} className={`approval-row${x.bad ? " bad" : ""}`} to={x.to}>
        <span className="approval-label">{x.label}</span><span className="approval-count">{x.n}</span><span className="alert-go">{t("dash.review")}</span><Icon name="arrow" size={16} />
      </Link>
    );
    const showAttendance = can("attendance.view") && !!home;

    body = (
      <>
        {kpis.length > 0 && <div className="kpis">{kpis}</div>}
        <div className="dash-cols">
          <div className="dash-stack">
            <section className="panel" aria-labelledby="dash-pending">
              <header><span className={`ico ${approvals.length ? "warn" : "ok"}`}><Icon name={approvals.length ? "clock" : "check"} size={18} /></span><h2 id="dash-pending">{t("dash.pending")}</h2></header>
              {approvals.length > 0 ? approvals.map(row) : <p className="muted" role="status">{t("dash.noPending")}</p>}
            </section>
            {attention.length > 0 ? (
              <section className="panel attention" aria-labelledby="dash-attn">
                <header><span className="ico warn"><Icon name="alert" size={18} /></span><h2 id="dash-attn">{t("dash.attention")}</h2></header>
                {attention.map(row)}
              </section>
            ) : approvals.length === 0 ? (
              <section className="panel allclear" role="status">
                <span className="ico ok"><Icon name="check" size={18} /></span>
                <div><h2>{t("dash.allClear")}</h2><p className="muted">{t("dash.allClearHint")}</p></div>
              </section>
            ) : null}
          </div>
          <div className="dash-stack">
            {showAttendance && <AttendanceCard unitId={home!.id} unitName={name(home!)} />}
            <QuickActions />
            <RecentActivity />
          </div>
        </div>
        {(regionRows.length > 1 || daily) && (
          <div className="charts">
            {regionRows.length > 1 && <ChartPanel icon="map" title={t("dash.byRegion")}><RegionChart rows={regionRows} /></ChartPanel>}
            {daily && (
              <ChartPanel icon="activity" title={t(range === 30 ? "dash.activity30d" : "dash.activity7d")} actions={<RangeSwitch value={range} onChange={setRange} />}>
                {series
                  ? <ActivityChart days={series} />
                  : longer.error
                    ? <ErrorNotice error={longer.error} />
                    : <div className="skeleton chart-skeleton" role="status" aria-busy="true" aria-label={t("common.loading")} />}
              </ChartPanel>
            )}
          </div>
        )}
        <h2 className="section-title">{t("dash.details")}</h2>
        <div className="grid">{panels.map((p) => <Panel key={p.title} icon={p.icon} title={p.title} rows={p.rows} meter={p.meter} />)}</div>
      </>
    );
  }

  return (
    <>
      <div className="dash-top">
        <div className="hero">
          <img src="/defence-force.jpg" alt="Puntland Defence Force emblem" width={64} height={64} />
          <div>
            <p className="muted">{t(greetingKey(now))}{first ? `, ${first}` : ""}</p>
            <h1>{t("dash.title")}</h1>
            <p className="muted dash-date">{formatLongDate(now, lang)} · {t("dash.todayHint")}</p>
          </div>
        </div>
        {n && (
          <ExportPdfButton filename="dashboard.pdf" build={() => ({
            title: t("dash.title"),
            sections: pdfSections.map((s) => ({ heading: s.title, columns: [{ header: "", width: 3 }, { header: "", width: 1, align: "right" as const }], rows: s.rows })),
          })} />
        )}
      </div>
      <ErrorNotice error={error} />
      {loading && !n ? <Skeleton label={t("common.loading")} /> : body}
    </>
  );
}
