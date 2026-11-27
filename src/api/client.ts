let csrfToken = "";

export interface FieldError { message: string; code: string }
export interface ErrorBody {
  code?: string; detail?: string; errors?: Record<string, FieldError[]> | FieldError[];
  /** Sent with `otp_required`: true when the server can email a recovery code for a lost authenticator app. */
  email_recovery?: boolean;
}

export class ApiError extends Error {
  status: number;
  body: ErrorBody;
  constructor(status: number, body: ErrorBody | null) {
    super(body?.detail ?? "Request failed");
    this.status = status;
    this.body = body ?? {};
  }
  get code(): string { return this.body.code ?? "error"; }
  /** First field-level error code, e.g. "weak_password", if this is a validation error. */
  get fieldCode(): string | undefined {
    const errs = this.body.errors;
    if (!errs) return undefined;
    if (Array.isArray(errs)) return errs[0]?.code;
    const first = Object.values(errs)[0];
    return first?.[0]?.code;
  }
  fieldCodes(field: string): string[] {
    const errs = this.body.errors;
    if (!errs || Array.isArray(errs)) return [];
    return (errs[field] ?? []).map((e) => e.code);
  }
}

/**
 * Step-up: the server answers `step_up_required` when a sensitive action needs a recent authenticator code. The app registers a
 * handler (a small dialog) that asks for the code; when it confirms, the original request is sent once more.
 */
type StepUpHandler = () => Promise<boolean>;
let stepUpHandler: StepUpHandler | null = null;
export function setStepUpHandler(handler: StepUpHandler | null): void { stepUpHandler = handler; }

async function withStepUp<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (e) {
    if (e instanceof ApiError && e.code === "step_up_required" && stepUpHandler && (await stepUpHandler())) return run();
    throw e;
  }
}

const unreachable = () => new ApiError(0, { code: "network", detail: "Network error" });

/**
 * The API always answers JSON (or 204). Anything else (an HTML fallback page from a static host with no API
 * behind it, or a proxy's 502 page) means the backend is not reachable, so report it as a network error
 * instead of letting callers treat an HTML page as data.
 */
export function isJsonResponse(res: Pick<Response, "headers">): boolean {
  return (res.headers.get("content-type") ?? "").toLowerCase().includes("json");
}

export async function refreshCsrf(): Promise<void> {
  if (import.meta.env.VITE_PREVIEW === "1") return; // the preview build has no server and no CSRF
  let r: Response;
  try {
    r = await fetch("/api/v1/auth/csrf/", { credentials: "same-origin" });
  } catch {
    throw unreachable();
  }
  if (!r.ok || !isJsonResponse(r)) throw unreachable();
  const data = (await r.json().catch(() => null)) as { csrf_token?: string } | null;
  if (!data?.csrf_token) throw unreachable();
  csrfToken = data.csrf_token;
}

interface Options { method?: "GET" | "POST" | "PATCH" | "DELETE"; body?: unknown; headers?: Record<string, string>; query?: Record<string, string | number | undefined | null> }

let lastApiAt = Date.now();
/** When the server last answered a request: every answer renews the server-side idle timer, which the idle warning needs to know. */
export const getLastApiAt = (): number => lastApiAt;

export function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  return withStepUp(() => apiOnce<T>(path, opts));
}

async function apiOnce<T>(path: string, opts: Options): Promise<T> {
  const method = opts.method ?? "GET";
  if (import.meta.env.VITE_PREVIEW === "1") {
    // Standalone preview: answer from the in-memory sample data instead of calling a server.
    const query: Record<string, string> = {};
    for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined && v !== null) query[k] = String(v);
    const { previewApi } = await import("../preview/mock");
    return (await previewApi(method, path, query, opts.body)) as T;
  }
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString() ? `?${params}` : "";
  const send = () =>
    fetch(`/api/v1${path}${qs}`, {
      method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(method !== "GET" ? { "X-CSRFToken": csrfToken } : {}),
        ...(opts.headers ?? {}),
      },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });

  let res: Response;
  try {
    res = await send();
    lastApiAt = Date.now();
    if (res.status === 403 && method !== "GET") {
      const peek = (await res.clone().json().catch(() => null)) as ErrorBody | null;
      if (peek?.detail && /CSRF/i.test(peek.detail)) {
        await refreshCsrf();
        res = await send();
      }
    }
  } catch {
    throw unreachable();
  }
  if (res.status === 204) return undefined as T;
  if (!isJsonResponse(res)) throw unreachable();
  const data = (await res.json().catch(() => null)) as unknown;
  if (!res.ok) throw new ApiError(res.status, data as ErrorBody | null);
  return data as T;
}

/** Multipart upload (CSV). The browser sets the multipart boundary, so no Content-Type header here. */
/** Preview build only: photos "uploaded" this session, kept in memory as object URLs (nothing is sent anywhere). */
export const previewPhotos = new Map<string, string>();

/** URL of a person's photo. In the preview build it is the in-memory preview; otherwise the API endpoint. */
export function photoUrl(personId: string, v: number): string {
  if (import.meta.env.VITE_PREVIEW === "1") return previewPhotos.get(personId) ?? "";
  return `/api/v1/personnel/${personId}/photo/?v=${v}`;
}

/** URL of the signed-in user's own avatar (a small thumbnail of the photo on their personnel record), or "" when there is none. */
export function myPhotoUrl(personnelId: string | null | undefined, v: number | null | undefined): string {
  if (v == null) return "";
  if (import.meta.env.VITE_PREVIEW === "1") return personnelId ? previewPhotos.get(personnelId) ?? "" : "";
  return `/api/v1/auth/me/photo/?v=${v}`;
}

export async function upload<T>(path: string, field: string, file: File, extra: Record<string, string> = {}): Promise<T> {
  if (import.meta.env.VITE_PREVIEW === "1") {
    const m = path.match(/^\/personnel\/([^/]+)\/photo\/upload\/$/);
    if (m) {
      const old = previewPhotos.get(m[1]);
      if (old) URL.revokeObjectURL(old);
      previewPhotos.set(m[1], URL.createObjectURL(file));
      return { has_photo: true } as T;
    }
    const { previewUpload } = await import("../preview/mock");
    return previewUpload() as T;
  }
  const form = new FormData();
  for (const [k, v] of Object.entries(extra)) form.append(k, v);
  form.append(field, file);
  const send = () => fetch(`/api/v1${path}`, {
    method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrfToken }, body: form });
  let res: Response;
  try {
    res = await send();
    if (res.status === 403) {
      const peek = (await res.clone().json().catch(() => null)) as ErrorBody | null;
      if (peek?.detail && /CSRF/i.test(peek.detail)) { await refreshCsrf(); res = await send(); }
    }
  } catch {
    throw unreachable();
  }
  if (!isJsonResponse(res)) throw unreachable();
  const data = (await res.json().catch(() => null)) as unknown;
  if (!res.ok) throw new ApiError(res.status, data as ErrorBody | null);
  return data as T;
}

export function downloadCsv(path: string, query: Record<string, string>, filename: string): Promise<void> {
  return withStepUp(() => downloadFileOnce(path, query, filename, "text/csv"));
}

/** Download a file the server builds (the unit report PDF, for example): same sign-in, step-up and error handling as the CSV exports. */
export function downloadWithQuery(path: string, query: Record<string, string>, filename: string, accept = "application/pdf"): Promise<void> {
  return withStepUp(() => downloadFileOnce(path, query, filename, accept));
}

async function downloadFileOnce(path: string, query: Record<string, string>, filename: string, accept: string): Promise<void> {
  if (import.meta.env.VITE_PREVIEW === "1") {
    const url = URL.createObjectURL(new Blob(["preview,sample\n"], { type: accept }));
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    return;
  }
  const params = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== ""));
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}?${params}`, { credentials: "same-origin", headers: { Accept: accept } });
  } catch {
    throw unreachable();
  }
  if (!res.ok) {
    if (!isJsonResponse(res)) throw unreachable();
    throw new ApiError(res.status, (await res.json().catch(() => null)) as ErrorBody | null);
  }
  if ((res.headers.get("content-type") ?? "").toLowerCase().includes("html")) throw unreachable();
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Fetch every page of a list endpoint (for exports). Refuses very large result sets rather than hammering the API. */
export async function fetchAll<T>(path: string, query: Record<string, string | number | undefined | null> = {}, max = 5000): Promise<T[]> {
  const out: T[] = [];
  for (let page = 1; ; page++) {
    const r = await api<{ count: number; next: string | null; results: T[] }>(path, { query: { ...query, page, page_size: 100 } });
    if (r.count > max) throw new ApiError(400, { code: "export_too_large" });
    out.push(...r.results);
    if (!r.next || r.results.length === 0) break;
  }
  return out;
}

/** Multipart POST with several fields (service documents). Same CSRF retry and error handling as upload(). */
export async function uploadForm<T>(path: string, form: FormData): Promise<T> {
  if (import.meta.env.VITE_PREVIEW === "1") throw new ApiError(0, { code: "network", detail: "Not available in the preview build" });
  const send = () => fetch(`/api/v1${path}`, { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrfToken }, body: form });
  let res: Response;
  try {
    res = await send();
    if (res.status === 403) {
      const peek = (await res.clone().json().catch(() => null)) as ErrorBody | null;
      if (peek?.detail && /CSRF/i.test(peek.detail)) { await refreshCsrf(); res = await send(); }
    }
  } catch {
    throw unreachable();
  }
  if (!isJsonResponse(res)) throw unreachable();
  const data = (await res.json().catch(() => null)) as unknown;
  if (!res.ok) throw new ApiError(res.status, data as ErrorBody | null);
  return data as T;
}

/** Download a protected file (service document) through the session; the server logs every download. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  if (import.meta.env.VITE_PREVIEW === "1") throw new ApiError(0, { code: "network", detail: "Not available in the preview build" });
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, { credentials: "same-origin" });
  } catch {
    throw unreachable();
  }
  if (!res.ok) {
    if (!isJsonResponse(res)) throw new ApiError(res.status, { code: res.status === 404 ? "not_found" : "error" });
    throw new ApiError(res.status, (await res.json().catch(() => null)) as ErrorBody | null);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
