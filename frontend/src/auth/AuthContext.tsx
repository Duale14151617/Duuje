import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, refreshCsrf } from "../api/client";
import type { Me } from "../api/types";
import { useI18n } from "../i18n";

interface Auth {
  me: Me | null;
  loading: boolean;
  /** True when the last attempt to reach the API failed at the network level (backend down or not deployed). */
  offline: boolean;
  login: (username: string, password: string, otp?: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
  can: (permission: string) => boolean;
}

const Ctx = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { setLang } = useI18n();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  const reload = useCallback(async () => {
    try {
      await refreshCsrf();
      const m = await api<Me>("/auth/me/");
      setMe(m);
      setOffline(false);
      setLang(m.preferred_language);
    } catch (e) {
      setMe(null);
      setOffline(e instanceof ApiError && e.code === "network");
    } finally {
      setLoading(false);
    }
  }, [setLang]);

  useEffect(() => { void reload(); }, [reload]);

  const login = useCallback(async (username: string, password: string, otp?: string) => {
    const m = await api<Me>("/auth/login/", { method: "POST", body: { username, password, otp } });
    await refreshCsrf(); // Django rotates the CSRF token on login
    setOffline(false);
    setMe(m);
    setLang(m.preferred_language);
  }, [setLang]);

  const logout = useCallback(async () => {
    try { await api("/auth/logout/", { method: "POST" }); } finally {
      setMe(null);
      await refreshCsrf();
    }
  }, []);

  const value = useMemo<Auth>(() => ({
    me, loading, offline, login, logout, reload,
    can: (p) => !!me && me.restrictions.length === 0 && me.permissions.includes(p),
  }), [me, loading, offline, login, logout, reload]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("AuthProvider missing");
  return ctx;
}
