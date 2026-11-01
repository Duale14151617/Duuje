import { Link } from "react-router-dom";
import type { EquipmentSummary, FleetAnalytics, PpeSummary } from "../api/types";
import { useI18n, type Key } from "../i18n";
import { ChartPanel } from "./DashboardCharts";
import { EmptyState } from "./ui";

interface Seg { value: number; cls: "c1" | "c2"; label: string }
export interface Bar { key: string; label: string; value: number; to?: string; segs?: Seg[] }

/** Horizontal bars with exact counts beside every bar, a hover/focus tooltip with the share and a drill-down link. Server numbers only. */
export function BarList({ rows, aria }: { rows: Bar[]; aria: string }) {
  const { t } = useI18n();
  const max = Math.max(1, ...rows.map((r) => r.value));
  const all = rows.reduce((n, r) => n + r.value, 0);
  if (rows.length === 0) return <p className="muted">{t("common.empty")}</p>;
  return (
    <ul className="hbars" aria-label={aria}>
      {rows.map((r) => {
        const segs: Seg[] = r.segs ?? [{ value: r.value, cls: "c1", label: r.label }];
        const share = all > 0 ? Math.round((r.value / all) * 100) : 0;
        return (
          <li key={r.key} className="hb-row">
            <span className="hb-label" title={r.label}>{r.to ? <Link to={r.to}>{r.label}</Link> : r.label}</span>
            <span className="hb-cell" tabIndex={0} aria-label={`${r.label}: ${r.value.toLocaleString()}`}>
              <span className="hb-track" aria-hidden="true">
                {segs.map((s) => <span key={s.label} className={`hb-seg ${s.cls}`} style={{ width: `${(s.value / max) * 100}%` }} />)}
              </span>
              <span className="hb-tip" role="tooltip">
                <b>{r.label}</b>
                {r.segs && r.segs.map((s) => <span key={s.label} className="hb-tip-row"><span className={`swatch ${s.cls}`} aria-hidden="true" />{s.label}<b>{s.value.toLocaleString()}</b></span>)}
                <span className="hb-tip-row total">{t("dash.regionTotal")}<b>{r.value.toLocaleString()}</b></span>
                <span className="muted">{t("dash.regionShare", { n: share })}</span>
                {r.to && <Link className="hb-tip-link" to={r.to}>{t("equip.drill")}</Link>}
              </span>
            </span>
            <span className="hb-nums"><b>{r.value.toLocaleString()}</b></span>
          </li>
        );
      })}
    </ul>
  );
}

function Stat({ label, value, to, warn }: { label: string; value: number | string; to?: string; warn?: boolean }) {
  const body = <><b>{typeof value === "number" ? value.toLocaleString() : value}</b> {label}</>;
  return <span className={warn ? "warnstat" : ""}>{to ? <Link to={to}>{body}</Link> : body}</span>;
}

const CONDITION_ORDER = ["new", "good", "fair", "poor", "unserviceable", "unknown"];
const conditionBars = (by: Record<string, number>, t: (k: Key) => string, link?: (c: string) => string): Bar[] =>
  CONDITION_ORDER.filter((c) => (by[c] ?? 0) > 0).map((c) => ({ key: c, label: t(`cond.${c}` as Key), value: by[c], to: link?.(c) }));

export function MoneyList({ rows, label }: { rows: { currency: string; total: string }[]; label: string }) {
  if (rows.length === 0) return null;
  return <p className="muted money-line">{label}: {rows.map((r) => `${r.currency || "—"} ${Number(r.total).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`).join(" · ")}</p>;
}

/** Fleet analytics: classification, condition, inspection and maintenance status, availability and (cost permission only) repair spend. */
export function FleetPanel({ f, unit }: { f: FleetAnalytics; unit?: string }) {
  const { t, name } = useI18n();
  const q = (extra: string) => `/vehicles?${unit ? `unit=${unit}&` : ""}${extra}`;
  if (f.total === 0) return <ChartPanel icon="truck" title={t("fleet.title")}><EmptyState icon="truck" title={t("veh.none")} /></ChartPanel>;
  return (
    <ChartPanel icon="truck" title={t("fleet.title")}>
      <div className="chart-stats">
        <Stat label={t("fleet.total")} value={f.total} to={q("")} />
        <Stat label={t("fleet.availablePct", { n: f.available_pct })} value={f.available} />
        <Stat label={t("fleet.requiringInspection")} value={f.requiring_inspection} to={q("needs_inspection=1")} warn={f.requiring_inspection > 0} />
        <Stat label={t("fleet.underMaintenance")} value={f.under_maintenance} to={q("under_maintenance=1")} warn={f.under_maintenance > 0} />
      </div>
      <h3 className="chart-sub">{t("fleet.byGroup")}</h3>
      <BarList aria={t("fleet.byGroup")} rows={f.by_group.filter((g) => g.count > 0).map((g) => ({ key: g.code, label: t(`fleet.group.${g.code}` as Key), value: g.count, to: q(`group=${g.code}`) }))} />
      <h3 className="chart-sub">{t("fleet.byCategory")}</h3>
      <BarList aria={t("fleet.byCategory")} rows={f.by_category.filter((c) => c.count > 0).map((c) => ({ key: c.code, label: name(c), value: c.count, to: q(`category=${c.code}`) }))} />
      <h3 className="chart-sub">{t("fleet.byCondition")}</h3>
      <BarList aria={t("fleet.byCondition")} rows={conditionBars(f.by_condition, t, (c) => q(`condition=${c}`))} />
      {f.expenditure.visible && <MoneyList rows={f.expenditure.by_currency} label={t("fleet.repairSpend")} />}
    </ChartPanel>
  );
}

export function PpePanel({ p }: { p: PpeSummary }) {
  const { t, name } = useI18n();
  const rows: Bar[] = p.by_category.filter((c) => c.in_store + c.held > 0).map((c) => ({
    key: c.code, label: name(c), value: c.in_store + c.held, to: "/ppe",
    segs: [{ value: c.held, cls: "c1" as const, label: t("ppe.withPersonnel") }, { value: c.in_store, cls: "c2" as const, label: t("ppe.inStore") }],
  }));
  return (
    <ChartPanel icon="lock" title={t("ppe.title")}>
      <div className="chart-stats">
        <Stat label={t("ppe.inStore")} value={p.in_store} to="/ppe" />
        <Stat label={t("ppe.withPersonnel")} value={p.with_personnel} to="/ppe" />
        <Stat label={t("ppe.inspectionsDue")} value={p.inspection.due} warn={p.inspection.overdue > 0} />
        <Stat label={t("ppe.damagedLost")} value={p.damaged + p.lost} warn={p.damaged + p.lost > 0} />
      </div>
      <BarList aria={t("ppe.title")} rows={rows} />
      <MoneyList rows={p.procurement.by_currency} label={t("ppe.procurement")} />
    </ChartPanel>
  );
}

export function EquipmentPanel({ e }: { e: EquipmentSummary }) {
  const { t } = useI18n();
  const status = Object.entries(e.by_status).filter(([, n]) => n > 0).map(([k, n]) => ({ key: k, label: t(`astatus.${k}` as Key), value: n, to: `/logistics?asset_status=${k}` }));
  return (
    <ChartPanel icon="box" title={t("equip.title")}>
      <div className="chart-stats">
        <Stat label={t("equip.assets")} value={e.assets} to="/logistics" />
        <Stat label={t("equip.inspectionDue")} value={e.inspection_due} to="/logistics?inspection_due=1" warn={e.inspection_overdue > 0} />
        <Stat label={t("equip.awaitingReplacement")} value={e.awaiting_replacement} to="/logistics?asset_condition=unserviceable" warn={e.awaiting_replacement > 0} />
        {e.pending_approvals.categories > 0 && <Stat label={t("equip.pendingApprovals")} value={e.pending_approvals.categories} to="/logistics" warn />}
      </div>
      <h3 className="chart-sub">{t("equip.byCondition")}</h3>
      <BarList aria={t("equip.byCondition")} rows={conditionBars(e.by_condition, t, (c) => `/logistics?asset_condition=${c}`)} />
      <h3 className="chart-sub">{t("equip.byStatus")}</h3>
      <BarList aria={t("equip.byStatus")} rows={status} />
      {e.acquisition.visible && <MoneyList rows={e.acquisition.by_currency} label={t("equip.acquisitionSpend")} />}
    </ChartPanel>
  );
}
