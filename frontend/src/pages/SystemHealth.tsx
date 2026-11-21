import { useState } from "react";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Loading, Notice, PageHeader } from "../components/ui";
import { useI18n, type Key } from "../i18n";
import { formatDateTime } from "../lib/format";

interface Line { code: string; status: "ok" | "warn" | "bad"; params: { at?: string; never?: boolean; not_set?: boolean } }
interface Health { generated_at: string; version: string; build: string; lines: Line[]; problems: number }

/** For user administrators: is email configured, is the nightly backup running, is anything left in a risky setting. */
export function SystemHealth() {
  const { t, lang } = useI18n();
  const health = useFetch<Health>("/system/health-check/");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function testEmail() {
    setBusy(true); setNote(null); setError(null);
    try {
      const r = await api<{ sent_to: string }>("/system/health-check/test-email/", { method: "POST" });
      setNote(t("health.testSent", { to: r.sent_to }));
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  const d = health.data;
  const sentence = (l: Line) => {
    const variant = l.code === "scheduler" && l.params.not_set ? "notset" : l.status;
    return t(`health.${l.code}.${variant}` as Key, { date: l.params.at ? formatDateTime(l.params.at, lang) : "" });
  };
  return (
    <>
      <PageHeader title={t("health.title")} subtitle={t("health.intro")} actions={<button type="button" className="secondary" onClick={() => health.reload()}>{t("health.recheck")}</button>} />
      <ErrorNotice error={health.error ?? error} />
      {health.loading && !d ? <Loading variant="table" /> : null}
      {d && (
        <>
          <Notice kind={d.problems ? "warn" : "info"}>{d.problems ? t("health.problems", { n: d.problems }) : t("health.allGood")}</Notice>
          <ul className="list">
            {d.lines.map((l) => (
              <li key={l.code} className="item">
                <div className="row row-between">
                  <b>{t(`health.${l.code}.title` as Key)}</b>
                  <Chip tone={l.status === "ok" ? "ok" : l.status === "warn" ? "warn" : "bad"}>{t(`health.status.${l.status}` as Key)}</Chip>
                </div>
                <div className="muted">{sentence(l)}</div>
                {l.code === "email" && (
                  <button type="button" className="secondary" style={{ marginTop: ".4rem" }} disabled={busy} onClick={() => void testEmail()}>{t("health.testEmail")}</button>
                )}
              </li>
            ))}
          </ul>
          {note ? <Notice kind="info">{note}</Notice> : null}
          <p className="muted">{t("health.version", { version: d.version, build: d.build || "-", date: formatDateTime(d.generated_at, lang) })}</p>
        </>
      )}
    </>
  );
}
