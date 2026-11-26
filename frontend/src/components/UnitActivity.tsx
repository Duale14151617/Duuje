import { Link } from "react-router-dom";
import type { UnitProfile } from "../api/types";
import { useI18n, type Key } from "../i18n";
import { BarRow } from "./OrgBits";
import { Notice } from "./ui";

function Tiles({ items }: { items: { label: string; value: number | string }[] }) {
  return (
    <div className="org-tiles">
      {items.map((i) => <div key={i.label} className="org-tile"><b>{i.value}</b><span className="muted">{i.label}</span></div>)}
    </div>
  );
}

/** What a unit is doing: attendance today and vehicles.
 *  Every block comes from the module's own records; a block the viewer's role may not see arrives as null. */
export function UnitActivity({ profile }: { profile: UnitProfile }) {
  const { t } = useI18n();
  const a = profile.activity;
  const hidden = !a.attendance || !a.vehicles;
  return (
    <>
      <p className="muted">{t("act.window", { days: a.window_days })}</p>

      {a.attendance && (
        <div className="card">
          <h2>{t("act.attendance")}</h2>
          {a.attendance.reported === 0 ? <p className="muted">{t("act.notReported")}</p> : (
            <Tiles items={[{ label: t("act.present"), value: a.attendance.present }, { label: t("act.absent"), value: a.attendance.absent },
              { label: t("act.onLeave"), value: a.attendance.on_leave }]} />
          )}
          <p><Link to="/attendance">{t("act.openRegister")}</Link></p>
        </div>
      )}

      {a.vehicles && (
        <div className="card">
          <h2>{t("act.vehicles")} ({a.vehicles.total})</h2>
          {a.vehicles.by_status.map((v) => (
            <BarRow key={v.status} label={statusLabel(t, v.status)} value={v.count} max={Math.max(1, ...a.vehicles!.by_status.map((x) => x.count))} />
          ))}
          <p><Link to="/vehicles">{t("act.openRegister")}</Link></p>
        </div>
      )}

      {hidden && <Notice>{t("act.noAccess")}</Notice>}
    </>
  );
}

function statusLabel(t: (k: Key) => string, status: string): string {
  const label = t(`vstatus.${status}` as Key);
  return label.startsWith("vstatus.") ? status.replace(/_/g, " ") : label;
}
