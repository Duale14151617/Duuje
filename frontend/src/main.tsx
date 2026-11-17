import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { I18nProvider } from "./i18n";
import { en } from "./i18n/en";
import { so } from "./i18n/so";
import { setPoliceBrand } from "./lib/brand";
import { ThemeProvider } from "./theme/ThemeContext";
import { registerServiceWorker } from "./pwa/install";
import "./styles.css";

registerServiceWorker();

// One codebase serves the Army and the Police deployments. The server says which one this is, and the few place-name strings
// are replaced before the first render. Army is the default and needs no change; any failure keeps the built-in text.
async function applyProfile(): Promise<void> {
  try {
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 2500);
    const r = await fetch("/api/v1/profile/", { signal: ctrl.signal });
    window.clearTimeout(timer);
    if (!r.ok) return;
    const p = (await r.json()) as { profile?: string; name_en?: string; name_so?: string };
    if (!p.profile || p.profile === "army" || !p.name_en || !p.name_so) return;
    const E = en as unknown as Record<string, string>;
    const S = so as unknown as Record<string, string>;
    const army = "Puntland Defence Forces HQ";
    for (const k of Object.keys(E)) if (E[k].includes(army)) E[k] = E[k].split(army).join(p.name_en);
    for (const k of Object.keys(S)) if (S[k].includes(army)) S[k] = S[k].split(army).join(p.name_so);
    document.title = p.name_en;
    document.documentElement.dataset.profile = p.profile;
    if (p.profile === "police") {
      setPoliceBrand();
      E["inst.ministry"] = "Judicial oversight.";
      S["inst.ministry"] = "Kormeerka garsoorka.";
    }
  } catch {
    /* keep the built-in names */
  }
}

function start(): void {
  createRoot(document.getElementById("root") as HTMLElement).render(
    <StrictMode>
      <ThemeProvider>
        <I18nProvider>
          <AuthProvider>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </AuthProvider>
        </I18nProvider>
      </ThemeProvider>
    </StrictMode>,
  );
}

void applyProfile().finally(start);
