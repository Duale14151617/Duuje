import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { get } from "./api";

export type Me = {
  id: string; email: string; displayName: string; mfaEnabled: boolean; emailVerified?: boolean; isTechnician: boolean;
  platform: { companyVerify: boolean; technicianVerify: boolean; catalog: boolean; support: boolean };
  companies: { id: string; displayName: string; verification: string; roles: string[] }[];
};
export const MeContext = createContext<{ me: Me; reload: () => void } | null>(null);
export const useMe = () => useContext(MeContext)!;
export const isPlatform = (m: Me) => Object.values(m.platform).some(Boolean);

export const errText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong.");

export function useLoad<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!!path);
  const load = useCallback(() => {
    if (!path) return;
    setLoading(true);
    get<T>(path).then((d) => { setData(d); setError(""); }).catch((e) => setError(errText(e))).finally(() => setLoading(false));
  }, [path]);
  useEffect(load, [load]);
  return { data, error, loading, reload: load };
}

// Runs an async action, surfacing the error text; returns true on success.
export function useAction() {
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState("");
  const run = async (fn: () => Promise<unknown>, ok = "") => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); setNotice(ok); return true; } catch (e) { setError(errText(e)); return false; } finally { setBusy(false); }
  };
  return { run, error, busy, notice };
}

export const Status = ({ value }: { value: string }) => <span className={`pill ${value}`}>{value}</span>;
export const Msg = ({ error, notice }: { error?: string; notice?: string }) => (
  <>{error ? <div className="error" role="alert">{error}</div> : null}{notice ? <div className="notice">{notice}</div> : null}</>
);
export const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : "");
