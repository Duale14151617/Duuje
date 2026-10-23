import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, refreshCsrf } from "./client";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const html = (status = 200) => new Response("<!doctype html><html></html>", { status, headers: { "Content-Type": "text/html" } });

afterEach(() => vi.unstubAllGlobals());

describe("api client when the backend is not reachable", () => {
  it("treats an HTML fallback page (static host, no API) as a network error, not as data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(html()));
    const err = await api("/auth/me/").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("network");
  });
  it("treats a proxy error page as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(html(502)));
    const err = await api("/auth/me/").catch((e: unknown) => e);
    expect((err as ApiError).code).toBe("network");
  });
  it("treats a failed fetch as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const err = await api("/auth/me/").catch((e: unknown) => e);
    expect((err as ApiError).code).toBe("network");
  });
  it("refreshCsrf rejects with a network error on an HTML page and accepts a real token", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(html()));
    await expect(refreshCsrf()).rejects.toMatchObject({ code: "network" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ csrf_token: "abc" })));
    await expect(refreshCsrf()).resolves.toBeUndefined();
  });
});

describe("api client with a working backend", () => {
  it("returns parsed JSON and keeps API error bodies intact", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json({ ok: 1 })).mockResolvedValueOnce(json({ code: "not_authenticated" }, 401)));
    expect(await api("/x/")).toEqual({ ok: 1 });
    const err = await api("/x/").catch((e: unknown) => e);
    expect((err as ApiError).status).toBe(401);
    expect((err as ApiError).code).toBe("not_authenticated");
  });
  it("returns undefined for 204", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    expect(await api("/x/", { method: "DELETE" })).toBeUndefined();
  });
});
