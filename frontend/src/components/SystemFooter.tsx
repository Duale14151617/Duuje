import { useEffect, useState } from "react";
import { useFetch } from "../api/useFetch";
import { useI18n } from "../i18n";

interface Status { status: "operational" | "degraded"; version: string; build: string; support: string }

/** A support contact as a link when it is clearly an email address or a phone number, otherwise plain text. */
function Support({ value }: { value: string }) {
  const v = value.trim();
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return <a href={`mailto:${v}`}>{v}</a>;
  if (/^\+?[\d\s()-]{6,}$/.test(v)) return <a href={`tel:${v.replace(/[\s()-]/g, "")}`}>{v}</a>;
  return <>{v}</>;
}

/** Footer for signed-in pages: whether the system is healthy, which version is running, and who to contact. Facts come from an
 *  endpoint that needs a sign-in. If they cannot be loaded the footer still shows the name, never an error. */
export function SystemFooter() {
  const { t } = useI18n();
  const s = useFetch<Status>("/system/status/");
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);

  const d = s.data;
  const state = !online ? "offline" : d ? d.status : null;
  return (
    <footer className="sysfooter muted small">
      {state && (
        <span className={`sys-state ${state}`} role="status">
          <span className="sys-dot" aria-hidden="true" />
          {t(state === "operational" ? "sys.operational" : state === "degraded" ? "sys.degraded" : "sys.offline")}
        </span>
      )}
      <span>{t("app.name")} · {t("app.footer")}</span>
      {d?.version && <span>{t("sys.version")} {d.version}{d.build ? ` (${d.build})` : ""}</span>}
      {d?.support && <span>{t("sys.support")}: <Support value={d.support} /></span>}
    </footer>
  );
}
