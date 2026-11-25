import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import { pendingCount } from "./vault";

/** Reminds the officer that entries are waiting on this device (count only; reading it needs no passphrase). */
export function usePendingCount(): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    const read = () => { void pendingCount().then((c) => { if (live) setN(c); }); };
    read();
    const timer = window.setInterval(read, 5000);
    window.addEventListener("online", read);
    return () => { live = false; window.clearInterval(timer); window.removeEventListener("online", read); };
  }, []);
  return n;
}

export function PendingBanner({ count }: { count: number }) {
  const { t } = useI18n();
  if (count === 0) return null;
  return <div className="preview-banner" role="status">{t("off.pending", { n: count })} <Link to="/offline-desk">{t("off.pendingOpen")}</Link></div>;
}
