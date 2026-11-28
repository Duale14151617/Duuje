import { useFetch } from "../api/useFetch";
import { useI18n } from "../i18n";
import { formatDateTime } from "../lib/format";
import { Chip, EmptyState, ErrorNotice, Loading } from "./ui";

type Row = { id: string; at: string; action: string; outcome: string; ip: string | null; by_admin: boolean };

/** Account page: the person's own recent security activity (from the audit log), so a sign-in or change they did not make stands out. */
export function MyActivity() {
  const { t, tr, lang } = useI18n();
  const list = useFetch<{ results: Row[] }>("/auth/activity/");
  const label = (r: Row) => {
    const key = `activity.${r.action.replace(/\./g, "_")}${r.outcome === "success" ? "" : "_failed"}`;
    return tr(key) ?? r.action;
  };
  return (
    <section className="card" id="activity">
      <h2>{t("activity.title")}</h2>
      <p className="muted">{t("activity.intro")}</p>
      <ErrorNotice error={list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <EmptyState compact title={t("activity.none")} />}
      <ul className="list">
        {list.data?.results.map((r) => (
          <li key={r.id} className="item row row-between">
            <span>
              {r.outcome === "success" ? label(r) : <>{label(r)} <Chip tone="warn">{t("activity.failed")}</Chip></>}
              {r.by_admin && <> <Chip tone="draft">{t("activity.byAdmin")}</Chip></>}
              {r.ip ? <span className="muted"> · {r.ip}</span> : null}
            </span>
            <span className="muted">{formatDateTime(r.at, lang)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
