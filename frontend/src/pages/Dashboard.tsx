import { Link } from "react-router-dom";
import type { Dashboard as Data } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Icon, type IconName } from "../components/Icon";
import { ErrorNotice, Loading } from "../components/ui";
import { useI18n } from "../i18n";
import { ExportPdfButton } from "../components/ExportPdfButton";

type Row = [label: string, value: number, tone?: string];

function Kpi({ icon, label, value, tone = "" }: { icon: IconName; label: string; value: number; tone?: string }) {
  return (
    <div className={`kpi ${tone}`}>
      <span className={`ico ${tone}`}><Icon name={icon} /></span>
      <span className="num">{value.toLocaleString()}</span>
      <span className="lbl">{label}</span>
    </div>
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

export function Dashboard() {
  const { t } = useI18n();
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

    const panels: { icon: IconName; title: string; rows: Row[]; meter?: number }[] = [];
    if (n.personnel) panels.push({ icon: "users", title: t("dash.personnelTitle"), meter: activeShare,
      rows: [plain("dash.total", n.personnel.total), plain("dash.activePersonnel", n.personnel.active)] });
    if (n.scope) panels.push({ icon: "map", title: t("dash.scopeTitle"),
      rows: [plain("dash.units", n.scope.units_in_scope), plain("dash.regions", n.scope.regions_in_scope), plain("dash.branchCommands", n.scope.branch_commands_in_scope)] });
    if (n.ranks) panels.push({ icon: "award", title: t("dash.ranksTitle"),
      rows: [warn("dash.draft", n.ranks.draft), plain("dash.approved", n.ranks.approved)] });
    if (n.reports) panels.push({ icon: "file", title: t("dash.reportsTitle"),
      rows: [plain("dash.myOpen", n.reports.my_open), ...(n.reports.awaiting_review !== undefined ? [warn("dash.awaiting", n.reports.awaiting_review)] : [])] });
    if (n.logistics) panels.push({ icon: "box", title: t("dash.logisticsTitle"),
      rows: [warn("dash.lowStock", n.logistics.low_stock), warn("dash.assetsAttention", n.logistics.assets_attention)] });
    if (n.training) panels.push({ icon: "cap", title: t("dash.trainingTitle"),
      rows: [plain("dash.inProgress", n.training.in_progress), plain("dash.enrolled", n.training.enrolled)] });
    if (n.accounts) panels.push({ icon: "lock", title: t("dash.accountsTitle"),
      rows: [plain("dash.activeUsers", n.accounts.active), plain("dash.disabledUsers", n.accounts.disabled),
        warn("dash.noMfa", n.accounts.privileged_without_mfa, n.accounts.privileged_without_mfa > 0 ? "bad" : "")] });
    if (n.audit) panels.push({ icon: "activity", title: t("dash.auditTitle"),
      rows: [plain("dash.events", n.audit.events_24h), warn("dash.failedLogins", n.audit.failed_logins_24h), warn("dash.denied", n.audit.denied_24h)] });
    panels.push({ icon: "file", title: t("dash.demoTitle"),
      rows: [plain("dash.personnel", n.demo.personnel_records), plain("dash.requests", n.demo.pending_requests),
        plain("dash.reports", n.demo.reports_awaiting_review), plain("dash.training", n.demo.training_completions_30d)] });
    pdfSections = panels.map((p) => ({ title: p.title, rows: p.rows.map(([l, v]) => [l, v.toLocaleString()] as [string, string]) }));

    body = (
      <>
        <div className="kpis">
          {n.personnel && <Kpi icon="users" label={t("dash.personnelTitle")} value={n.personnel.total} />}
          {n.personnel && <Kpi icon="check" label={t("dash.activePersonnel")} value={n.personnel.active} />}
          {n.scope && <Kpi icon="layers" label={t("dash.units")} value={n.scope.units_in_scope} />}
          {n.ranks && <Kpi icon="award" label={t("dash.approved")} value={n.ranks.approved} />}
          {n.reports?.awaiting_review !== undefined && <Kpi icon="file" label={t("dash.awaiting")} value={n.reports.awaiting_review} tone={n.reports.awaiting_review > 0 ? "warn" : ""} />}
          {n.logistics && <Kpi icon="box" label={t("dash.lowStock")} value={n.logistics.low_stock} tone={n.logistics.low_stock > 0 ? "warn" : ""} />}
          {n.training && <Kpi icon="cap" label={t("dash.inProgress")} value={n.training.in_progress} />}
          {n.accounts && <Kpi icon="lock" label={t("dash.activeUsers")} value={n.accounts.active} />}
        </div>
        {attention.length > 0 && (
          <section className="panel attention">
            <header><span className="ico warn"><Icon name="alert" size={18} /></span><h2>{t("dash.attention")}</h2></header>
            {attention.map((x) => (
              <Link key={x.label} className="alert-row" to={x.to}><span>{x.label}</span><b>{x.n}</b><Icon name="arrow" size={16} /></Link>
            ))}
          </section>
        )}
        <h2 className="section-title">{t("dash.details")}</h2>
        <div className="grid">{panels.map((p) => <Panel key={p.title} {...p} />)}</div>
        <p className="muted small">{t("dash.demoBanner")}</p>
      </>
    );
  }

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div className="hero">
          <p className="muted">{t("dash.welcome")}{first ? `, ${first}` : ""}</p>
          <h1>{t("dash.title")}</h1>
        </div>
        {n && (
          <ExportPdfButton filename="dashboard.pdf" build={() => ({
            title: t("dash.title"),
            sections: pdfSections.map((s) => ({ heading: s.title, columns: [{ header: "", width: 3 }, { header: "", width: 1, align: "right" as const }], rows: s.rows })),
          })} />
        )}
      </div>
      <ErrorNotice error={error} />
      {loading && !n ? <Loading /> : body}
    </>
  );
}
