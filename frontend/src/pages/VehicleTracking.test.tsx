// @vitest-environment jsdom
// The Vehicle tracking page against a mocked API: latest positions, the no-map fallback, silent vehicles, zones and trackers.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { VehicleTracking } from "./VehicleTracking";

vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ can: () => true, reload: vi.fn(), me: null, loading: false, offline: false }) }));

const veh = { id: "v1", vehicle_id: "VEH-000001", plate: "PL-001", make: "Toyota", model: "Hilux" };
const pos = { id: "p1", vehicle: veh, latitude: "11.280000", longitude: "49.180000", accuracy_m: 10, place: "Bosaso", source: "tracker", recorded_at: "2026-11-20T08:00:00Z",
  age_minutes: 5, stale: false, note: "", void: false, version: 1 };

let urls: string[] = [];
beforeEach(() => {
  urls = [];
  vi.stubGlobal("fetch", vi.fn((input: string) => {
    const path = String(input).split("?")[0];
    urls.push(path);
    const body: unknown =
      path.endsWith("/auth/csrf/") ? { csrf_token: "t" } :
      path.endsWith("/map/config/") ? { available: false } :
      path.endsWith("/vehicle-tracking/latest/") ? { results: [pos] } :
      path.endsWith("/vehicle-tracking/silent/") ? { hours: 24, vehicles: [{ ...veh, id: "v2", vehicle_id: "VEH-000002", never: true, last_seen_at: null, age_minutes: null }], trackers: [] } :
      path.endsWith("/vehicles/") ? { count: 1, next: null, previous: null, results: [veh] } :
      { results: [] };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("VehicleTracking page", () => {
  it("shows the latest position and the plain plot when this server has no map file", async () => {
    render(<I18nProvider><MemoryRouter><VehicleTracking /></MemoryRouter></I18nProvider>);
    await waitFor(() => expect(screen.getAllByText(/VEH-000001/).length).toBeGreaterThan(0));
    expect(screen.getByRole("img", { name: "positions" })).toBeTruthy();
    expect(urls.some((u) => u.endsWith("/map/config/"))).toBe(true);
  });

  it("lists silent vehicles and loads zones and trackers", async () => {
    render(<I18nProvider><MemoryRouter><VehicleTracking /></MemoryRouter></I18nProvider>);
    await waitFor(() => expect(screen.getAllByText(/VEH-000002/).length).toBeGreaterThan(0));
    expect(urls.some((u) => u.endsWith("/vehicle-tracking/geofences/"))).toBe(true);
    expect(urls.some((u) => u.endsWith("/vehicle-tracking/trackers/"))).toBe(true);
  });
});
