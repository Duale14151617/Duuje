import { useEffect, useState } from "react";
import { Icon } from "../components/Icon";
import { useI18n } from "../i18n";

// "Install app" support. The browser fires `beforeinstallprompt` once the app qualifies; we keep the event
// (imported from main.tsx so the listener exists before React mounts) and let the user trigger it from a button.
interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferred: InstallPromptEvent | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as InstallPromptEvent;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    notify();
  });
}

function isStandalone(): boolean {
  return window.matchMedia("(display-mode: standalone)").matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

/** Registers the service worker (production builds only). Pages and API responses are never cached by it. */
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* installing is optional; the site works without it */ });
  });
}

export function InstallButton({ className = "icon-btn", showLabel = false }: { className?: string; showLabel?: boolean }) {
  const { t } = useI18n();
  const [, bump] = useState(0);
  useEffect(() => {
    const l = () => bump((n) => n + 1);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
  if (isStandalone()) return null; // already running as an installed app

  async function onClick() {
    if (deferred) {
      const ev = deferred;
      deferred = null;
      await ev.prompt();
      await ev.userChoice;
      notify();
      return;
    }
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
    window.alert(t(ios ? "pwa.ios" : window.isSecureContext ? "pwa.manual" : "pwa.https"));
  }

  return (
    <button type="button" className={className} onClick={() => void onClick()} aria-label={t("pwa.install")} title={t("pwa.install")}>
      <Icon name="download" size={18} />
      {showLabel && <span>{t("pwa.install")}</span>}
    </button>
  );
}
