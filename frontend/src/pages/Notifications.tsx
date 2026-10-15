import { Link } from "react-router-dom";
import { useState } from "react";
import { api } from "../api/client";
import type { NotificationItem, Page } from "../api/types";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, formatDate, Loading, Pager } from "../components/ui";
import { useI18n, type Key } from "../i18n";

export function Notifications() {
  const { t, lang } = useI18n();
  const [page, setPage] = useState(1);
  const list = useFetch<Page<NotificationItem>>("/notifications/", { page });
  const [error, setError] = useState<unknown>(null);

  async function markRead(id: string) {
    try { await api(`/notifications/${id}/read/`, { method: "POST" }); list.reload(); } catch (err) { setError(err); }
  }
  async function markAll() {
    try { await api("/notifications/read-all/", { method: "POST" }); list.reload(); } catch (err) { setError(err); }
  }

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "1rem" }}>
        <h1 style={{ margin: 0 }}>{t("note.title")}</h1>
        <button className="secondary" onClick={() => void markAll()}>{t("note.markAll")}</button>
      </div>
      <ErrorNotice error={error ?? list.error} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data && list.data.results.length === 0 && <p>{t("note.empty")}</p>}
      <ul className="list">
        {list.data?.results.map((n) => (
          <li key={n.id} className="item" style={n.read_at ? { opacity: 0.7 } : undefined}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <b>{t(`nkind.${n.kind}` as Key)}</b>
              {!n.read_at && <Chip tone="draft">•</Chip>}
            </div>
            <div>
              {n.submission
                ? <Link to={`/reports/${n.submission.id}`} onClick={() => void markRead(n.id)}>{n.submission.title}</Link>
                : <span className="muted">{t("note.noAccess")}</span>}
            </div>
            <div className="muted">{formatDate(n.created_at, lang)}</div>
          </li>
        ))}
      </ul>
      {list.data && <Pager page={page} count={list.data.count} pageSize={25} onPage={setPage} />}
    </>
  );
}
