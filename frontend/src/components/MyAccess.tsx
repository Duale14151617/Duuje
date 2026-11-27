import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import { Chip, EmptyState, formatDate } from "./ui";

/** Account page: the roles this login holds, the unit each applies to, any service branch limit and when it ends. */
export function MyAccess() {
  const { me } = useAuth();
  const { t, lang, name } = useI18n();
  const rows = me?.assignments ?? [];
  return (
    <section className="card">
      <h2>{t("myaccess.title")}</h2>
      {rows.length === 0 ? <EmptyState compact title={t("myaccess.none")} /> : (
        <ul className="list">
          {rows.map((a) => (
            <li key={a.id} className="item">
              <strong>{name(a.role)}</strong>{a.role.is_privileged && <> <Chip tone="approved">{t("myaccess.privileged")}</Chip></>}
              <div className="muted">
                {name(a.org_unit)}{a.branch ? ` · ${name(a.branch)}` : ""}
                {a.valid_until ? ` · ${t("myaccess.until", { date: formatDate(a.valid_until, lang) })}` : ""}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
