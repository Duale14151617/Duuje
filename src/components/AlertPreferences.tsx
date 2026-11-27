import { useState } from "react";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useI18n, type Key } from "../i18n";
import { ErrorNotice, Loading, Notice } from "./ui";

interface Prefs { email_ok: boolean; enabled: boolean; kinds: { kind: string; title: string; on: boolean }[] }

/** Switches for the event emails a person wants (vehicle crosses a zone, weapon lost, tracker silent, death reported).
 *  Only the alerts their role allows are listed, and they go to the verified email address only. */
export function AlertPreferences() {
  const { t } = useI18n();
  const prefs = useFetch<Prefs>("/alerts/preferences/");
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function toggle(kind: string) {
    if (!prefs.data) return;
    const on = new Set(prefs.data.kinds.filter((k) => k.on).map((k) => k.kind));
    if (on.has(kind)) on.delete(kind); else on.add(kind);
    setBusy(true); setError(null); setSaved(false);
    try {
      await api("/alerts/preferences/", { method: "PATCH", body: { kinds: [...on] } });
      prefs.reload();
      setSaved(true);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  const d = prefs.data;
  return (
    <section className="card">
      <h2>{t("alerts.title")}</h2>
      <ErrorNotice error={prefs.error ?? error} />
      {!d ? (prefs.error ? null : <Loading />) : (
        <>
          <p className="muted">{t("alerts.intro")}</p>
          {!d.enabled && <Notice kind="warn">{t("alerts.off")}</Notice>}
          {!d.email_ok && <Notice kind="warn">{t("alerts.needEmail")}</Notice>}
          {d.kinds.length === 0 ? <p className="muted">{t("alerts.none")}</p> : d.kinds.map((k) => (
            <label key={k.kind} className="row" style={{ gap: ".5rem" }}>
              <input type="checkbox" style={{ width: "auto", minHeight: 0 }} checked={k.on} disabled={busy} onChange={() => void toggle(k.kind)} />
              <span>{t(`alerts.kind.${k.kind}` as Key)}</span>
            </label>
          ))}
          {saved && <Notice>{t("alerts.saved")}</Notice>}
        </>
      )}
    </section>
  );
}
