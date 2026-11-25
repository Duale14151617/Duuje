import { api, ApiError } from "../api/client";
import { listItems, putItem, removeItem, type QueueItem } from "./vault";

export interface SyncResult { sent: number; attention: number; stopped: "network" | "auth" | null }
const OFFLINE_EVENT_KINDS = ["welfare", "medical", "visit", "property", "statement", "note", "review"] as const;
export const offlineEventKinds = OFFLINE_EVENT_KINDS;

/** Server message for an item that cannot be accepted (kept in the queue, never dropped). */
function problemOf(e: ApiError): string {
  const field = Array.isArray(e.body.errors) ? e.body.errors[0] : e.body.errors ? Object.values(e.body.errors)[0]?.[0] : undefined;
  return field?.message ?? e.body.detail ?? `Error ${e.status}`;
}

async function send(item: QueueItem): Promise<{ register_no?: string }> {
  // Every request carries the item id as client_ref, so sending twice (a dropped connection) never creates a second record.
  if (item.kind === "booking") {
    return api<{ register_no?: string }>("/detention/", { method: "POST", body: { ...item.payload, client_ref: item.id, offline: true } });
  }
  return api<{ register_no?: string }>(`/detention/${item.target}/event/`, {
    method: "POST", body: { ...item.payload, client_ref: item.id, offline: true },
  });
}

/** Sends the queue oldest first (a booking must reach the server before later notes on that person). */
export async function syncQueue(onProgress?: () => void): Promise<SyncResult> {
  const result: SyncResult = { sent: 0, attention: 0, stopped: null };
  const items = (await listItems()).filter((i) => i.state === "pending");
  for (const item of items) {
    try {
      const res = await send(item);
      await removeItem(item.id);
      result.sent += 1;
      if (item.kind === "booking") lastAssigned.push({ label: item.label, no: res.register_no ?? "" });
    } catch (e) {
      if (e instanceof ApiError && e.code === "network") { result.stopped = "network"; break; }
      if (e instanceof ApiError && (e.status === 401 || (e.status === 403 && e.code === "not_authenticated"))) { result.stopped = "auth"; break; }
      const problem = e instanceof ApiError ? problemOf(e) : "Unknown error";
      await putItem({ ...item, state: "attention", problem });
      result.attention += 1;
    }
    onProgress?.();
  }
  return result;
}

/** Register numbers the server gave to bookings in the last sync, so the officer can write them in the paper register. */
export const lastAssigned: { label: string; no: string }[] = [];
