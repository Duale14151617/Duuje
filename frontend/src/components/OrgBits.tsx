import { Link } from "react-router-dom";
import type { OrgBucket, OrgOffice } from "../api/types";
import { useI18n } from "../i18n";

/** Total / active / inactive tiles. Active = status "active"; inactive = every other status. */
export function StatTiles({ b, extra }: { b: OrgBucket; extra?: { label: string; value: number }[] }) {
  const { t } = useI18n();
  const items = [{ label: t("org2.total"), value: b.total }, { label: t("org2.active"), value: b.active },
    { label: t("org2.inactive"), value: b.inactive }, ...(extra ?? [])];
  return (
    <div className="org-tiles">
      {items.map((i) => <div key={i.label} className="org-tile"><b>{i.value}</b><span className="muted">{i.label}</span></div>)}
    </div>
  );
}

/** One horizontal bar: label, bar scaled to `max`, value. */
export function BarRow({ label, value, max, to, sub }: { label: string; value: number; max: number; to?: string; sub?: string }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="org-bar">
      <span className="org-bar-label">{to ? <Link to={to}>{label}</Link> : label}{sub ? <span className="muted"> {sub}</span> : null}</span>
      <span className="org-bar-track" aria-hidden="true"><span className="org-bar-fill" style={{ width: `${value > 0 ? pct : 0}%` }} /></span>
      <b className="org-bar-value">{value}</b>
    </div>
  );
}

/** Holder of an office: rank and name, or a neutral note when the viewer's role may not see names. */
export function Holder({ office }: { office: OrgOffice | null }) {
  const { t, name } = useI18n();
  if (!office) return <span className="muted">{t("org2.vacant")}</span>;
  if (!office.holder) return <span className="muted">{t("uo.holderHidden")}</span>;
  return <Link to={`/personnel/${office.holder.id}`}>{name(office.holder.rank)} {office.holder.full_name}</Link>;
}
