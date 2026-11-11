// Thin typed client. The token lives in memory (and sessionStorage so a refresh keeps you signed in for the tab only).
const BASE = "/api";
let token: string | null = sessionStorage.getItem("token");

export const auth = {
  get token() { return token; },
  set(t: string | null) { token = t; t ? sessionStorage.setItem("token", t) : sessionStorage.removeItem("token"); },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function parse(res: Response) {
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401 && token) { auth.set(null); window.location.assign("/login"); }
    const fallback = res.status === 403 ? "Not allowed (403). Your account lacks permission for this, or you belong to this company (reviewers cannot decide on their own company)."
      : res.status === 401 ? "Session expired (401). Sign out and sign in again."
      : res.status === 404 ? "Not found (404)."
      : `Request failed (${res.status})`;
    throw new ApiError(res.status, body?.error ?? body?.title ?? fallback);
  }
  return body;
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return parse(res);
}
export const get = <T = any>(p: string) => api<T>("GET", p);
export const post = <T = any>(p: string, b?: unknown) => api<T>("POST", p, b ?? {});
export const put = <T = any>(p: string, b?: unknown) => api<T>("PUT", p, b ?? {});

// Multipart upload (the browser sets the boundary, so no Content-Type header here).
export async function upload<T = any>(path: string, form: FormData): Promise<T> {
  const res = await fetch(BASE + path, { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: form });
  return parse(res);
}

// Documents are only readable with the bearer token, so fetch the bytes and open them as a blob.
export async function openFile(url: string) {
  const res = await fetch(BASE + url, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new ApiError(res.status, "Could not open the file.");
  const blob = await res.blob();
  window.open(URL.createObjectURL(blob), "_blank", "noopener");
}

export type Login = { token?: string; mfaRequired?: boolean; mfaToken?: string };

// Sign-out helper: revokes every session in the background. keepalive lets the request finish even after the page navigates away,
// so the person never waits for a slow or sleeping server.
export function revokeSessions() {
  if (!token) return;
  try {
    fetch(BASE + "/auth/logout-all", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: "{}" }).catch(() => {});
  } catch { /* ignore */ }
}
