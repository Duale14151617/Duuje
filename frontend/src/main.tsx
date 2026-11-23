import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { I18nProvider } from "./i18n";
import { ThemeProvider } from "./theme/ThemeContext";
import { registerServiceWorker } from "./pwa/install";
import "./styles.css";

registerServiceWorker();

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
