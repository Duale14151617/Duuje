import { useState } from "react";
import { Link } from "react-router-dom";
import type { ChartNode, OrgAnalytics } from "../api/types";
import { useFetch } from "../api/useFetch";
import { BarRow, StatTiles } from "../components/OrgBits";
import { Chip, ErrorNotice, Loading } from "../components/ui";
import { useI18n, type Key } from "../i18n";

function Node({ node, depth }: { node: ChartNode; depth: number }) {
  const { t, name } = useI18n();
  const [open, setOpen] = useState(depth < 1);
  const kids = node.children.length > 0;
  return (
    <li>
      <div className="org-node">
        {kids ? <button type="button" className="secondary tog" aria-expanded={open} aria-label={name(node)} onClick={() => setOpen(!open)}>{open ? "−" : "+"}</button>
          : <span className="tog-gap" />}
        <Link to={`/units/${node.id}`}>{name(node)}</Link>
        <Chip>{t(`org2.role.${node.formation_role}` as Key)}</Chip>
        <span className="muted">{node.code}</span>
        {!node.is_active && <Chip tone="draft">{t("tree.inactive")}</Chip>}
        <span className="counts muted">
          <span>{t("org2.total")}: <b>{node.total}</b></span>
          <span>{t("org2.active")}: <b>{node.active}</b></span>
          <span>{t("org2.inactive")}: <b>{node.inactive}</b></span>
        </span>
      </div>
      {kids && open && <ul>{node.children.map((c) => <Node key={c.id} node={c} depth={depth + 1} />)}</ul>}
    </li>
  );
}

/** Expandable organizational chart: General Headquarters > commands > brigades > battalions, each with its strength. */
export function OrgChart() {
  const { t } = useI18n();
  const chart = useFetch<{ count: number; roots: ChartNode[]; counts_complete: boolean }>("/organization/units/chart/");
  if (chart.loading && !chart.data) return <Loading />;
  return (
    <div className="org-chart">
      <ErrorNotice error={chart.error} />
      {chart.data && !chart.data.counts_complete && <p className="muted">{t("uo.noCounts")}</p>}
      {chart.data && chart.data.roots.length === 0 && <p className="muted">{t("org2.chartEmpty")}</p>}
      <ul>{chart.data?.roots.map((n) => <Node key={n.id} node={n} depth={0} />)}</ul>
    </div>
  );
}

/** Organization-wide dashboard: totals, strength by brigade and battalion, department staffing, leadership and ranks. */
export function OrgAnalyticsView() {
  const { t, name } = useI18n();
  const res = useFetch<OrgAnalytics>("/organization/analytics/");
  if (res.loading && !res.data) return <Loading />;
  if (res.error || !res.data) return <ErrorNotice error={res.error} />;
  const d = res.data;
  const group = (role: string) => d.by_formation[role] ?? [];
  const maxOf = (rows: { total: number }[]) => Math.max(0, ...rows.map((r) => r.total));
  const roles = ["regional", "brigade", "battalion"] as const;
  return (
    <>
      {!d.counts_complete && <p className="muted">{t("uo.noCounts")}</p>}
      <div className="card">
        <h2>{t("org2.totals")}</h2>
        <StatTiles b={d.totals} />
        <p className="muted">{t("org2.definition")}</p>
        <p className="muted">{Object.entries(d.totals.by_status).map(([k, v]) => `${t(`pstatus.${k}` as Key)} ${v}`).join(" · ")}</p>
      </div>
      {roles.map((role) => group(role).length > 0 && (
        <div className="card" key={role}>
          <h2>{t(`org2.by.${role}` as Key)}</h2>
          {group(role).map((u) => <BarRow key={u.id} label={name(u)} sub={`${u.code} · ${t("org2.active")} ${u.active} / ${t("org2.inactive")} ${u.inactive}`}
                                          value={u.total} max={maxOf(group(role))} to={`/units/${u.id}`} />)}
        </div>
      ))}
      <div className="card">
        <h2>{t("org2.deptStaffing")}</h2>
        <table>
          <thead><tr><th>{t("dept.department")}</th><th>{t("org2.total")}</th><th>{t("org2.active")}</th><th>{t("org2.establishedIn")}</th><th>{t("org2.withHead")}</th><th>{t("org2.withDeputy")}</th></tr></thead>
          <tbody>
            {d.departments.map((x) => (
              <tr key={x.department.id}><td>{name(x.department)}{x.department.restricted ? <> <Chip tone="draft">{t("dept.restricted")}</Chip></> : null}</td>
                <td>{x.total}</td><td>{x.active}</td><td>{x.established_in}</td><td>{x.with_head}</td><td>{x.with_deputy}</td></tr>
            ))}
            <tr><td className="muted">{t("dept.unassigned")}</td><td>{d.unassigned_department.total}</td><td>{d.unassigned_department.active}</td><td /><td /><td /></tr>
          </tbody>
        </table>
      </div>
      <div className="card">
        <h2>{t("org2.leadershipSummary")}</h2>
        <p>{t("org2.leadershipLine", { units: d.leadership.units, commander: d.leadership.with_commander, deputy: d.leadership.with_deputy })}</p>
        {d.leadership.vacancies.length > 0 && (
          <>
            <h3>{t("org2.vacancies")} ({d.leadership.vacancies_total})</h3>
            <table><tbody>{d.leadership.vacancies.map((v) => (
              <tr key={v.id}><td><Link to={`/units/${v.id}`}>{name(v)}</Link> <span className="muted">{v.code}</span></td>
                <td>{v.missing.map((m) => t(`org2.missing.${m}` as Key)).join(", ")}</td></tr>
            ))}</tbody></table>
          </>
        )}
      </div>
      <div className="card">
        <h2>{t("org2.byRank")}</h2>
        {d.by_rank.map((r) => <BarRow key={r.rank.id} label={`${r.rank.code} ${name(r.rank)}`} value={r.count} max={Math.max(0, ...d.by_rank.map((x) => x.count))} />)}
      </div>
    </>
  );
}
