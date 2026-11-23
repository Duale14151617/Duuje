import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { api, ApiError } from "./client";

type Query = Record<string, string | number | undefined | null>;

export function useFetch<T>(path: string | null, query?: Query) {
  const { reload: reloadAuth } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);
  const key = JSON.stringify([path, query]);

  useEffect(() => {
    if (path === null) { setLoading(false); return; }
    let live = true;
    setLoading(true);
    api<T>(path, { query })
      .then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e: unknown) => {
        if (!live) return;
        const err = e instanceof ApiError ? e : new ApiError(0, { code: "network" });
        setError(err);
        if (err.code === "not_authenticated") void reloadAuth();
      })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);

  return { data, error, loading, reload: () => setTick((n) => n + 1) };
}
