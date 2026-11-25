import { Link } from "react-router-dom";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { useI18n, type Key } from "../i18n";
import { Icon, type IconName } from "./Icon";

interface Tile { to: string; icon: IconName; label: Key; show: boolean; sub?: string }
interface CustodySummary { in_custody: number; overdue: number }
interface HandoverWaiting { for_me: number }

/**
 * "My work": shortcuts to the pages this person's role is for, ahead of the general dashboard, so a station officer opens
 * straight onto the register and a tax head onto the tax register. Built from permissions only (the server still decides
 * what each page returns). Not shown to the super administrator, who already sees everything in the menu and dashboard.
 */
export function MyWork() {
  const { can } = useAuth();
  const { t } = useI18n();
  const custody = can("detention.view");
  const summary = useFetch<CustodySummary>(custody ? "/detention/summary/" : null);
  const handover = useFetch<HandoverWaiting>(custody ? "/shift-handovers/waiting/" : null);
  if (can("system.full_access")) return null;

  const s = summary.data;
  const candidates: Tile[] = [
    { to: "/detention", icon: "lock", label: "nav.detention", show: custody,
      sub: s ? t("my.custodySub", { held: s.in_custody, overdue: s.overdue }) : undefined },
    { to: "/shift-handover", icon: "swap", label: "nav.handover", show: custody && can("detention.manage"),
      sub: handover.data && handover.data.for_me > 0 ? t("my.handoverSub", { n: handover.data.for_me }) : undefined },
    { to: "/occurrence-book", icon: "list", label: "nav.occurrence", show: custody && can("detention.manage") },
    { to: "/custody-oversight", icon: "building", label: "nav.oversight", show: can("detention.verify") || can("detention.incident_review") },
    { to: "/custody-incidents", icon: "alert", label: "nav.incidents", show: can("detention.incident_review") },
    { to: "/tax", icon: "list", label: "nav.tax", show: can("tax.view") },
    { to: "/attendance", icon: "check", label: "nav.attendance", show: can("attendance.record") },
    { to: "/weapons", icon: "lock", label: "nav.hub.weapons", show: can("weapons.manage") },
    { to: "/vehicles", icon: "truck", label: "nav.vehicles", show: can("vehicles.create") || can("vehicles.edit") },
    { to: "/logistics", icon: "box", label: "nav.logistics", show: can("logistics.manage") || can("logistics.approve") },
    { to: "/payroll", icon: "list", label: "nav.payroll", show: can("payroll.view") },
    { to: "/training", icon: "cap", label: "nav.training", show: can("training.configure") || can("training.report") },
    { to: "/reports", icon: "file", label: "nav.reports", show: can("reports.submit") },
  ];
  const tiles = candidates.filter((x) => x.show).slice(0, 6);
  if (tiles.length === 0) return null;

  return (
    <section aria-labelledby="my-work">
      <h2 className="section-title" id="my-work">{t("my.title")}</h2>
      <div className="kpis">
        {tiles.map((x) => (
          <Link key={x.to} to={x.to} className="kpi">
            <span className="ico"><Icon name={x.icon} /></span>
            <span className="lbl">{t(x.label)}</span>
            {x.sub ? <span className="sub">{x.sub}</span> : null}
          </Link>
        ))}
      </div>
    </section>
  );
}
