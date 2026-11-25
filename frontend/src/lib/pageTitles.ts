import { useEffect } from "react";
import type { Key } from "../i18n";

/**
 * What the browser tab says on each screen: "Personnel · Puntland Police HQ". Matching is by longest path prefix, so a detail screen
 * (/personnel/123) inherits its list's title and only the rare exception needs its own line. A route that is not listed here keeps
 * the plain application name rather than showing something wrong.
 */
const TITLES: [string, Key][] = [
  ["/", "nav.dashboard"],
  ["/account", "nav.account"],
  ["/notifications", "nav.notifications"],
  ["/organization", "nav.organization"],
  ["/structure", "nav.structure"],
  ["/structure-changes", "nav.structureChanges"],
  ["/org-settings", "nav.orgSettings"],
  ["/tree", "nav.tree"],
  ["/institutions", "nav.institutions"],
  ["/units", "nav.units"],
  ["/my-record", "nav.myRecord"],
  ["/personnel", "nav.personnel"],
  ["/personnel-report", "nav.personnelReport"],
  ["/credentials", "nav.credentials"],
  ["/search", "nav.search"],
  ["/change-requests", "nav.changeRequests"],
  ["/attendance", "nav.attendance"],
  ["/leave", "nav.leave"],
  ["/promotion", "nav.promotion"],
  ["/fitness", "nav.fitness"],
  ["/training", "nav.training"],
  ["/ranks", "nav.ranks"],
  ["/payroll", "nav.payroll"],
  ["/survivors", "nav.survivors"],
  ["/reports", "nav.reports"],
  ["/summary", "nav.summary"],
  ["/schedules", "nav.schedules"],
  ["/analytics", "nav.analytics"],
  ["/tasks", "nav.tasks"],
  ["/due-soon", "nav.dueSoon"],
  ["/logistics", "nav.logistics"],
  ["/ammunition", "nav.ammunition"],
  ["/accountability", "nav.accountability"],
  ["/ammo-control", "nav.ammoControl"],
  ["/ppe", "nav.ppe"],
  ["/weapons", "nav.weapons"],
  ["/inventories", "nav.inventories"],
  ["/holdings", "nav.holdings"],
  ["/vehicles", "nav.vehicles"],
  ["/equipment", "nav.equipment"],
  ["/vehicle-log", "vlog.title"],
  ["/vehicle-tracking", "nav.tracking"],
  ["/food", "nav.food"],
  ["/detention", "nav.detention"],
  ["/occurrence-book", "nav.occurrence"],
  ["/shift-handover", "nav.handover"],
  ["/custody-facilities", "nav.facilities"],
  ["/custody-oversight", "nav.oversight"],
  ["/custody-incidents", "nav.incidents"],
  ["/offline-desk", "off.nav"],
  ["/tax", "nav.tax"],
  ["/tax-oversight", "nav.taxOversight"],
  ["/users", "nav.users"],
  ["/integrations", "nav.integrations"],
  ["/audit", "nav.audit"],
  ["/system-health", "nav.systemHealth"],
];

/** The i18n key for the screen at this path, or null when it is not listed. */
export function titleKeyFor(pathname: string): Key | null {
  let best: [string, Key] | null = null;
  for (const row of TITLES) {
    const [p] = row;
    const hit = p === "/" ? pathname === "/" : pathname === p || pathname.startsWith(`${p}/`);
    if (hit && (!best || p.length > best[0].length)) best = row;
  }
  return best ? best[1] : null;
}

/** "Page · App name", or just the app name when there is no page. */
export const tabTitle = (page: string | null, app: string): string => (page ? `${page} · ${app}` : app);

/** Sets the browser tab title while the calling screen is shown (for screens outside the signed-in layout, such as sign-in). */
export function useDocumentTitle(page: string | null, app: string): void {
  useEffect(() => { document.title = tabTitle(page, app); }, [page, app]);
}
