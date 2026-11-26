import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useI18n, type Key } from "../i18n";
import { Icon, type IconName } from "./Icon";

interface Tile { to: string; icon: IconName; label: Key; show: boolean; sub?: string }

/**
 * "My work": shortcuts to the pages this person's role is for, ahead of the general dashboard, so a unit officer opens
 * straight onto attendance and a store officer onto logistics. Built from permissions only (the server still decides
 * what each page returns). Not shown to the super administrator, who already sees everything in the menu and dashboard.
 */
export function MyWork() {
  const { can } = useAuth();
  const { t } = useI18n();
  if (can("system.full_access")) return null;

  const candidates: Tile[] = [
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
