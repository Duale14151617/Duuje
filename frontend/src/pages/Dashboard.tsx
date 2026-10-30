import { Link } from "react-router-dom";
import type { Dashboard as Data } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Icon, type IconName } from "../components/Icon";
import { ErrorNotice } from "../components/ui";
import { useI18n } from "../i18n";
import { ExportPdfButton } from "../components/ExportPdfButton";
import { ActivityChart, ChartPanel, RegionChart } from "../components/DashboardCharts";

type Row = [label: string, value: number, tone?: string];

function Kpi({ icon, label, value, to, suffix = "", tone = "" }:
  { icon: IconName; label: string; value: number; to: string; suffix?: string; tone?: string }) {
  return (
    <Link to={to} className={`kpi ${tone}`}>
      <span className={`ico ${tone}`}><Icon name={icon} /></span>
      <span className="num">{value.toLocaleString()}{suffix}</span>
      <span className="lbl">{label}</span>
    </Link>
  );
}

function Panel({ icon, title, rows, meter }: { icon: IconName; title: string; rows: Row[]; meter?: number }) {
  return (
    <section className="panel">
      <header><span className="ico"><Icon name={icon} size={18} /></span><h2>{title}</h2></header>
      {meter !== undefined && <div className="meter" aria-hidden="true"><span style={{ width: `${Math.round(meter * 100)}%` }} /></div>}
      {rows.map(([label, value, tone]) => (
        <div className="prow" key={label}><span>{label}</span><b className={tone ?? ""}>{value.toLocaleString()}</b></div>
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
  const { t, name } = useI18n();
  const { me } = useAuth();
  const { data: n, error, loading } = useFetch<Data>("/dashboard/");
  const warn = (k: Parameters<typeof t>[0], v: number, tone = v > 0 ? "warn" : ""): Row => [t(k), v, tone];
  const plain = (k: Parameters<typeof t>[0], v: number): Row => [t(k), v];
  const first = me?.full_name.split(" ")[0];

  let body = null;
  let pdfSections: { title: string; rows: [string, string][] }[] = [];
  if (n) {
    const attention = [
      { to: "/reports", label: t("dash.awaiting"), n: n.reports?.awaiting_review ?? 0 },
      { to: "/logistics", label: t("dash.lowStock"), n: n.logistics?.low_stock ?? 0 },
      { to: "/logistics", label: t("dash.assetsAttention"), n: n.logistics?.assets_attention ?? 0 },
      { to: "/users", label: t("dash.noMfa"), n: n.accounts?.privileged_without_mfa ?? 0 },
      { to: "/audit", label: t("dash.failedLogins"), n: n.audit?.failed_logins_24h ?? 0 },
      { to: "/audit", label: t("dash.denied"), n: n.audit?.denied_24h ?? 0 },
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
    pdfSections = panels.map((p) => ({ title: p.title, rows: (p.pdf ?? p.rows).map(([l, v]) => [l, v.toLocaleString()] as [string, string]) }));
    if (regionRows.length > 1) pdfSections.push({ title: t("dash.byRegion"),
      rows: regionRows.map((r) => [r.code === null ? t("level.headquarters") : name(r), r.total.toLocaleString()] as [string, string]) });

    // Four headline cards, each a shortcut to its page. The first ones that apply to this role are shown.
    const openReports = n.reports?.awaiting_review ?? n.reports?.my_open;
    const kpis = [
      n.personnel && <Kpi key="p" to="/personnel" icon="users" label={t("dash.personnelTitle")} value={n.personnel.total} />,
      activeShare !== undefined && <Kpi key="a" to="/personnel" icon="check" label={t("dash.activeShare")} value={Math.round(activeShare * 100)} suffix="%" />,
      n.scope && <Kpi key="u" to="/organization" icon="layers" label={t("dash.units")} value={n.scope.units_in_scope} />,
      openReports !== undefined && <Kpi key="r" to="/reports" icon="file" label={n.reports?.awaiting_review !== undefined ? t("dash.awaiting") : t("dash.myOpen")}
        value={openReports} tone={n.reports?.awaiting_review ? "warn" : ""} />,
      n.accounts && <Kpi key="c" to="/users" icon="lock" label={t("dash.activeUsers")} value={n.accounts.active} />,
      n.training && <Kpi key="t" to="/training" icon="cap" label={t("dash.inProgress")} value={n.training.in_progress} />,
    ].filter(Boolean).slice(0, 4);

    body = (
      <>
        {attention.length > 0 ? (
          <section className="panel attention" aria-labelledby="dash-attn">
            <header><span className="ico warn"><Icon name="alert" size={18} /></span><h2 id="dash-attn">{t("dash.attention")}</h2></header>
            {attention.map((x) => (
              <Link key={x.label} className="alert-row" to={x.to}><span>{x.label}</span><b>{x.n}</b><Icon name="arrow" size={16} /></Link>
            ))}
          </section>
        ) : (
          <section className="panel allclear" role="status">
            <span className="ico ok"><Icon name="check" size={18} /></span>
            <div><h2>{t("dash.allClear")}</h2><p className="muted">{t("dash.allClearHint")}</p></div>
          </section>
        )}
        {kpis.length > 0 && <div className="kpis">{kpis}</div>}
        {(regionRows.length > 1 || daily) && (
          <div className="charts">
            {regionRows.length > 1 && <ChartPanel icon="map" title={t("dash.byRegion")}><RegionChart rows={regionRows} /></ChartPanel>}
            {daily && <ChartPanel icon="activity" title={t("dash.activity7d")}><ActivityChart days={daily} /></ChartPanel>}
          </div>
        )}
        <h2 className="section-title">{t("dash.details")}</h2>
        <div className="grid">{panels.map((p) => <Panel key={p.title} icon={p.icon} title={p.title} rows={p.rows} meter={p.meter} />)}</div>
      </>
    );
  }

  return (
    <>
      <div className="dash-head">
        <div className="hero">
          <img src="/defence-force.jpg" alt="Puntland Defence Force emblem" width={64} height={64} />
          <div>
            <p className="muted">{t("dash.welcome")}{first ? `, ${first}` : ""}</p>
            <h1>{t("dash.title")}</h1>
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
