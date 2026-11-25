import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useI18n } from "../i18n";
import { describeDevice } from "../lib/device";
import { formatDateTime } from "../lib/format";
import { EmptyState, ErrorNotice, Loading } from "./ui";

interface Row { id: string; current: boolean; ua: string; ip: string; started_at: string | null; last_seen_at: string }

/** Account page: every place this account is signed in, with a way to end the ones the person does not recognise. */
export function MySessions() {
  const { t, lang } = useI18n();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<{ results: Row[] }>("/auth/sessions/").then((r) => setRows(r.results)).catch((e) => setError(e));
  }, []);
  useEffect(load, [load]);

  async function act(work: () => Promise<unknown>, confirm?: string) {
    if (confirm && !window.confirm(confirm)) return;
    setBusy(true); setError(null);
    try { await work(); load(); } catch (e) { setError(e); } finally { setBusy(false); }
  }

  const others = (rows ?? []).filter((r) => !r.current).length;
  return (
    <section className="card">
      <h2>{t("sess.heading")}</h2>
      <p className="muted">{t("sess.intro")}</p>
      <ErrorNotice error={error} />
      {rows === null ? <Loading /> : rows.length === 0 ? <EmptyState compact icon="lock" title={t("sess.none")} /> : (
        <ul className="list sess-list">
          {rows.map((r) => (
            <li key={r.id} className="row" style={{ justifyContent: "space-between", gap: ".75rem", alignItems: "center" }}>
              <span>
                <b>{describeDevice(r.ua) || t("sess.unknown")}</b>{r.current ? <span className="chip ok" style={{ marginLeft: ".5rem" }}>{t("sess.thisDevice")}</span> : null}
                <br />
                <small className="muted">
                  {r.ip ? `${r.ip} · ` : ""}{r.started_at ? t("sess.started", { date: formatDateTime(r.started_at, lang) }) : ""}
                  {" · "}{t("sess.lastSeen", { date: formatDateTime(r.last_seen_at, lang) })}
                </small>
              </span>
              {!r.current && (
                <button type="button" className="secondary" disabled={busy}
                        onClick={() => void act(() => api(`/auth/sessions/${r.id}/`, { method: "DELETE" }))}>{t("sess.end")}</button>
              )}
            </li>
          ))}
        </ul>
      )}
      {others > 0 && (
        <button type="button" className="secondary" disabled={busy}
                onClick={() => void act(() => api("/auth/sessions/", { method: "POST" }), t("sess.confirmOthers"))}>{t("sess.endOthers", { n: others })}</button>
      )}
    </section>
  );
}
