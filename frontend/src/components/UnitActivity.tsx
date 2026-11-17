import { Link } from "react-router-dom";
import type { UnitProfile } from "../api/types";
import { useI18n, type Key } from "../i18n";
import { timeAgo } from "../lib/time";
import { BarRow } from "./OrgBits";
import { Notice } from "./ui";

function Tiles({ items }: { items: { label: string; value: number | string }[] }) {
  return (
    <div className="org-tiles">
      {items.map((i) => <div key={i.label} className="org-tile"><b>{i.value}</b><span className="muted">{i.label}</span></div>)}
    </div>
  );
}

/** What a unit (a station above all) is doing: its jail, Occurrence Book, custody, attendance today and vehicles.
 *  Every block comes from the module's own records; a block the viewer's role may not see arrives as null. */
export function UnitActivity({ profile }: { profile: UnitProfile }) {
  const { t, name, lang } = useI18n();
  const a = profile.activity;
  const hidden = !a.occurrence || !a.custody || !a.attendance || !a.vehicles;
  const maxCat = Math.max(1, ...(a.occurrence?.by_category.map((c) => c.count) ?? [1]));
  return (
    <>
      <p className="muted">{t("act.window", { days: a.window_days })}</p>

      {profile.facilities.length > 0 && (
        <div className="card">
          <h2>{t("act.jails")}</h2>
          <table>
            <tbody>{profile.facilities.map((f) => (
              <tr key={f.id}>
                <td>{name(f)} <span className="muted">{f.code}</span></td>
                <td><b>{f.in_custody}</b> {t("act.held")}{f.capacity != null ? <span className="muted"> / {f.capacity} {t("act.capacity")}</span> : null}</td>
                <td className="muted">{f.operated_by}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {a.custody && (
        <div className="card">
          <h2>{t("act.custody")}</h2>
          <Tiles items={[{ label: t("act.inCustody"), value: a.custody.in_custody }, { label: t("act.booked"), value: a.custody.booked_30_days },
            { label: t("act.released"), value: a.custody.released_30_days }, { label: t("act.transferred"), value: a.custody.transferred_30_days }]} />
          {a.custody.held.length > 0 && (
            <table>
              <thead><tr><th>{t("act.heldNow")}</th><th>{t("act.reason")}</th><th>{t("act.cell")}</th><th /></tr></thead>
              <tbody>{a.custody.held.map((h) => (
                <tr key={h.id}><td>{h.detainee_name} <span className="muted">{h.register_no}</span></td><td>{h.reason}</td><td>{h.cell || "-"}</td>
                  <td className="muted">{timeAgo(h.booked_at, lang)}</td></tr>
              ))}</tbody>
            </table>
          )}
          <p><Link to="/detention">{t("act.openRegister")}</Link></p>
        </div>
      )}

      {a.occurrence && (
        <div className="card">
          <h2>{t("act.occurrence")}</h2>
          <Tiles items={[{ label: t("act.today"), value: a.occurrence.today }, { label: t("act.period"), value: a.occurrence.last_30_days }]} />
          {a.occurrence.by_category.map((c) => <BarRow key={c.category} label={t(`ob.cat.${c.category}` as Key)} value={c.count} max={maxCat} />)}
          <h3>{t("act.recent")}</h3>
          {a.occurrence.recent.length === 0 ? <p className="muted">{t("act.none")}</p> : (
            <table><tbody>{a.occurrence.recent.map((e) => (
              <tr key={e.id}><td><b>{e.ob_number}</b></td><td>{t(`ob.cat.${e.category}` as Key)}</td><td>{e.summary}</td>
                <td className="muted">{timeAgo(e.occurred_at, lang)}</td></tr>
            ))}</tbody></table>
          )}
          <p><Link to="/occurrence-book">{t("act.openRegister")}</Link></p>
        </div>
      )}

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
