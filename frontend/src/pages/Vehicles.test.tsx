// @vitest-environment jsdom
// Renders the vehicle screens against a mocked API and clicks through the main actions (no browser or server needed).
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { VehicleDetail, Vehicles } from "./Vehicles";

vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ can: () => true, reload: vi.fn(), me: null, loading: false, offline: false }) }));
vi.mock("../components/UnitPicker", () => ({ UnitPicker: ({ label }: { label: string }) => <div>{label}</div> }));

const cat = { id: "c1", code: "hilux_4x4", name_en: "Hilux 4x4", name_so: "Hilux 4x4" };
const unit = { id: "u1", code: "BN-1", name_en: "Battalion 1", name_so: "Urur 1" };
const row = {
  id: "11111111-1111-1111-1111-111111111111", vehicle_id: "VEH-000001", plate: "TEST-001", plate_status: "registered", category: cat, vehicle_type: "", make: "Toyota",
  model: "Hilux", year: 2015, org_unit: unit, driver: null, custodian: null, location: "Test depot", status: "operational", condition: "good", next_due_date: null,
  maintenance_overdue: false, disposal_pending: false, version: 3,
};
const detail = { ...row, notes: "", acquired_on: null, acquisition_ref: "", decommissioned_at: null, disposal: null, assignment_history: [],
  capabilities: { edit: true, transfer: true, dispose: true, approve: true, cost: true } };
const statuses = ["operational", "under_repair", "decommissioned", "on_loan"].map((code, i) => ({ id: `s${i}`, code, name_en: code === "on_loan" ? "On loan" : code, name_so: code, available: code === "operational", is_system: code !== "on_loan", active: true }));
const tally = { total: 2, by_category: [{ ...cat, count: 2 }], by_status: { on_loan: 1, operational: 1 }, without_driver: 2, without_custodian: 2, overdue_maintenance: 0, unavailable: 1 };

let calls: { url: string; method: string; body: unknown }[] = [];

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn((input: string, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const path = url.split("?")[0];
    const body: unknown =
      path.endsWith("/auth/csrf/") ? { csrf_token: "t" } :
      path.endsWith("/vehicles/categories/") ? { results: [cat] } :
      path.endsWith("/vehicles/statuses/") ? { results: statuses } :
      path.endsWith("/vehicles/summary/") ? { unit, total: 2, direct: tally, subordinate: { ...tally, total: 0 }, combined: tally, decommissioned: 0, by_child_unit: [{ unit, total: 2, direct: 2 }] } :
      path.endsWith("/vehicles/") ? { count: 1, next: null, previous: null, results: [row] } :
      path.endsWith("/history/") || path.endsWith("/maintenance/") || path.endsWith("/documents/") ? { results: [], cost_visible: true } :
      path.includes("/vehicles/1111") ? (method === "GET" ? detail : { ...row, version: 4 }) : {};
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const app = (path: string) => render(
  <I18nProvider><MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/vehicles" element={<Vehicles />} /><Route path="/vehicles/:id" element={<VehicleDetail />} />
  </Routes></MemoryRouter></I18nProvider>);

describe("vehicle screens", () => {
  it("lists vehicles with the summary for the chosen unit and a configured custom status", async () => {
    app("/vehicles?unit=u1");
    expect(await screen.findByText(/VEH-000001/)).toBeTruthy();
    expect(await screen.findByText("Combined (each vehicle counted once)")).toBeTruthy();
    expect((await screen.findAllByText("On loan")).length).toBeGreaterThan(0);  // custom status label comes from the server
    expect(calls.some((c) => c.url.includes("/vehicles/summary/") && c.url.includes("org_unit=u1"))).toBe(true);
  });

  it("changes a vehicle's status, sending the version it loaded", async () => {
    app("/vehicles/11111111-1111-1111-1111-111111111111");
    fireEvent.click(await screen.findByText("Change status"));
    const select = (await screen.findAllByRole("combobox"))[0] as HTMLSelectElement;
    await waitFor(() => expect(Array.from(select.options).map((o) => o.value)).toContain("on_loan"));
    expect(Array.from(select.options).map((o) => o.value)).not.toContain("decommissioned");  // only via the approval workflow
    fireEvent.change(select, { target: { value: "on_loan" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Lent to Battalion 2" } });
    fireEvent.click(screen.getByText("Apply"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/status/"))).toBe(true));
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/status/"))!;
    expect(post.body).toMatchObject({ version: 3, status: "on_loan", reason: "Lent to Battalion 2" });
  });
});
