import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { Lang, Named } from "../api/types";
import { en } from "./en";
import { so } from "./so";

export type Key = keyof typeof en;
const dicts: Record<Lang, Record<string, string>> = { en, so };

interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
  /** Lookup by dynamic key (e.g. `err.${code}`); undefined when missing. */
  tr: (key: string) => string | undefined;
  /** Localised name with English fallback (e.g. Somali name still pending). */
  name: (o: Named) => string;
}

const Ctx = createContext<I18n | null>(null);

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem("armyhq.lang");
    if (saved === "en" || saved === "so") return saved;
  } catch { /* storage unavailable */ }
  return navigator.language?.toLowerCase().startsWith("so") ? "so" : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    document.documentElement.lang = l;
    try { localStorage.setItem("armyhq.lang", l); } catch { /* ignore */ }
  }, []);
  const value = useMemo<I18n>(() => {
    const dict = dicts[lang];
    return {
      lang,
      setLang,
      t: (key, vars) => {
        let s = dict[key] ?? key;
        for (const [k, v] of Object.entries(vars ?? {})) s = s.replace(`{${k}}`, String(v));
        return s;
      },
      tr: (key) => dict[key],
      name: (o) => (lang === "so" && o.name_so ? o.name_so : o.name_en),
    };
  }, [lang, setLang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("I18nProvider missing");
  return ctx;
}
