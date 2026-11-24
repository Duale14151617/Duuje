import type { ReactNode } from "react";
import { useI18n } from "../i18n";
import { useTheme, type ThemeMode } from "./ThemeContext";

const svg = (children: ReactNode) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);

const ICONS: Record<ThemeMode, ReactNode> = {
  light: svg(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" /></>),
  dark: svg(<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />),
  system: svg(<><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></>),
};

export function ThemeToggle() {
  const { t } = useI18n();
  const { mode, setMode } = useTheme();
  const label: Record<ThemeMode, string> = { light: t("theme.light"), dark: t("theme.dark"), system: t("theme.system") };
  return (
    <div className="theme-toggle" role="radiogroup" aria-label={t("theme.label")}>
      {(["light", "system", "dark"] as ThemeMode[]).map((m) => (
        <button key={m} type="button" role="radio" aria-checked={mode === m} aria-label={label[m]} title={label[m]}
                className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
          {ICONS[m]}
        </button>
      ))}
    </div>
  );
}
