import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { NotificationItem, Page } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useI18n, type Key } from "../i18n";
import { timeAgo } from "../lib/time";
import { Icon } from "./Icon";

/** Bell in the top bar: unread count, and the latest few notifications in a small panel. The full list stays on /notifications.
 *  `count` comes from the layout (it already tracks it); `onChanged` asks the layout to refresh it after something is marked read. */
export function NotificationBell({ count, onChanged }: { count: number; onChanged: () => void }) {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const list = useFetch<Page<NotificationItem>>(open ? "/notifications/" : null, { page_size: 6 });

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [open]);

  async function markRead(id: string) {
    try { await api(`/notifications/${id}/read/`, { method: "POST" }); onChanged(); list.reload(); } catch { /* the full page reports errors */ }
  }
  async function markAll() {
    try { await api("/notifications/read-all/", { method: "POST" }); onChanged(); list.reload(); } catch { /* the full page reports errors */ }
  }

  const label = count > 0 ? t("note.bellUnread", { n: count }) : t("nav.notifications");
  return (
    <div className="bell" ref={box}>
      <button type="button" className="icon-btn bell-btn" aria-label={label} title={label} aria-haspopup="true" aria-expanded={open}
              onClick={() => setOpen((v) => !v)}>
        <Icon name="bell" size={18} />
        {count > 0 && <span className="bell-badge" aria-hidden="true">{count > 99 ? "99+" : count}</span>}
      </button>
      {open && (
        <div className="bell-panel" role="region" aria-label={t("nav.notifications")}>
          <div className="bell-head">
            <b>{t("note.title")}</b>
            {count > 0 && <button type="button" className="linklike" onClick={() => void markAll()}>{t("note.markAll")}</button>}
          </div>
          {list.loading && !list.data ? <p className="muted bell-empty" role="status">{t("common.loading")}</p> : null}
          {list.data && list.data.results.length === 0 && <p className="muted bell-empty">{t("note.empty")}</p>}
          <ul className="bell-list">
            {list.data?.results.map((n) => {
              const to = n.submission ? `/reports/${n.submission.id}` : n.kind === "new_address" ? "/account#activity" : n.kind === "due_digest" ? "/due-soon" : n.kind.startsWith("leave_") && n.leave ? "/leave" : "/notifications";
              const text = n.submission?.title ?? n.leave?.title ?? (n.kind === "new_address" ? t("note.newAddress") : n.kind === "due_digest" ? t("note.dueDigest") : t("note.noAccess"));
              return (
                <li key={n.id} className={n.read_at ? "read" : "unread"}>
                  <Link to={to} onClick={() => { setOpen(false); if (!n.read_at) void markRead(n.id); }}>
                    <span className="bell-kind">{t(`nkind.${n.kind}` as Key)}</span>
                    <span className="bell-text">{text}</span>
                    <time dateTime={n.created_at} className="muted">{timeAgo(n.created_at, lang)}</time>
                  </Link>
                </li>
              );
            })}
          </ul>
          <Link className="bell-all" to="/notifications" onClick={() => setOpen(false)}>{t("dash.viewAll")}</Link>
        </div>
      )}
    </div>
  );
}
