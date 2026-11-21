/**
 * Offline vault: an encrypted store on this device for records entered without internet.
 * Everything (queue and the station/in-custody snapshot) is encrypted with AES-GCM using a key derived from a passphrase the
 * officer chooses (PBKDF2-SHA256). The key lives only in memory: closing the tab locks the vault. The passphrase is never stored,
 * so a forgotten passphrase cannot be recovered (the officer wipes the vault; unsynced entries are then lost).
 * Only the number of waiting items is readable without the passphrase.
 */
export const PBKDF2_ITERATIONS = 600_000;
export const MIN_PASSPHRASE = 8;
const DB = "armyhq-offline";
type StoreName = "meta" | "items" | "snapshot";

export type ItemKind = "booking" | "event";
export interface QueueItem {
  id: string;                 // also the client_ref sent to the server (makes retries safe)
  kind: ItemKind;
  created_at: string;         // device clock when typed in
  label: string;              // what the officer sees in the queue
  payload: Record<string, unknown>;
  target?: string;            // event: server id of the detention record
  target_label?: string;
  state: "pending" | "attention";
  problem?: string;           // why it needs attention (server message/code)
  assigned_no?: string;       // register number given by the server after sync
}
export interface Snapshot {
  taken_at: string;
  stations: { id: string; name: string }[];
  in_custody: { id: string; register_no: string; detainee_name: string }[];
}

let key: CryptoKey | null = null;
export const isUnlocked = () => key !== null;
export const lock = () => { key = null; };

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      for (const s of ["meta", "items", "snapshot"] as StoreName[]) if (!db.objectStoreNames.contains(s)) db.createObjectStore(s);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function tx<T>(store: StoreName, mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  try {
    return await new Promise<T>((resolve, reject) => {
      const r = run(db.transaction(store, mode).objectStore(store));
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
  } finally { db.close(); }
}

const b64 = (u: Uint8Array) => btoa(String.fromCharCode(...u));
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const enc = new TextEncoder();

async function derive(pass: string, salt: Uint8Array, iterations: number): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", enc.encode(pass), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt: salt as BufferSource, iterations, hash: "SHA-256" }, base,
    { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}
async function seal(value: unknown): Promise<{ iv: string; data: string }> {
  if (!key) throw new Error("locked");
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, enc.encode(JSON.stringify(value))));
  return { iv: b64(iv), data: b64(data) };
}
async function unseal<T>(box: { iv: string; data: string }): Promise<T> {
  if (!key) throw new Error("locked");
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(box.iv) as BufferSource }, key, unb64(box.data) as BufferSource);
  return JSON.parse(new TextDecoder().decode(plain)) as T;
}

export const supported = () => typeof indexedDB !== "undefined" && typeof crypto !== "undefined" && !!crypto.subtle;
export async function exists(): Promise<boolean> {
  try { return (await tx("meta", "readonly", (s) => s.get("check"))) !== undefined; } catch { return false; }
}

/** First-time set-up. Stores a salt and an encrypted check value so a wrong passphrase is detected on unlock. */
export async function create(pass: string): Promise<void> {
  if (pass.length < MIN_PASSPHRASE) throw new Error("short");
  const salt = crypto.getRandomValues(new Uint8Array(16));
  key = await derive(pass, salt, PBKDF2_ITERATIONS);
  await tx("meta", "readwrite", (s) => s.put({ salt: b64(salt), iterations: PBKDF2_ITERATIONS }, "kdf"));
  await tx("meta", "readwrite", (s) => s.put(0, "count"));
  const box = await seal("armyhq-offline-ok");
  await tx("meta", "readwrite", (s) => s.put(box, "check"));
}

/** Returns false for a wrong passphrase. */
export async function unlock(pass: string): Promise<boolean> {
  const kdf = await tx<{ salt: string; iterations: number } | undefined>("meta", "readonly", (s) => s.get("kdf"));
  const check = await tx<{ iv: string; data: string } | undefined>("meta", "readonly", (s) => s.get("check"));
  if (!kdf || !check) return false;
  const k = await derive(pass, unb64(kdf.salt), kdf.iterations);
  const previous = key;
  key = k;
  try {
    if ((await unseal<string>(check)) !== "armyhq-offline-ok") throw new Error("bad");
    return true;
  } catch { key = previous; return false; }
}

export async function wipe(): Promise<void> {
  key = null;
  await new Promise<void>((resolve) => {
    const r = indexedDB.deleteDatabase(DB);
    r.onsuccess = () => resolve(); r.onerror = () => resolve(); r.onblocked = () => resolve();
  });
}

async function setCount() {
  const keys = await tx<IDBValidKey[]>("items", "readonly", (s) => s.getAllKeys());
  await tx("meta", "readwrite", (s) => s.put(keys.length, "count"));
}
/** Number of entries waiting; readable while locked (it reveals nothing about the records). */
export async function pendingCount(): Promise<number> {
  try { return (await tx<number | undefined>("meta", "readonly", (s) => s.get("count"))) ?? 0; } catch { return 0; }
}

export async function putItem(item: QueueItem): Promise<void> {
  const box = await seal(item);
  await tx("items", "readwrite", (s) => s.put(box, item.id));
  await setCount();
}
export async function listItems(): Promise<QueueItem[]> {
  const db = await open();
  try {
    const rows = await new Promise<{ iv: string; data: string }[]>((resolve, reject) => {
      const r = db.transaction("items", "readonly").objectStore("items").getAll();
      r.onsuccess = () => resolve(r.result as { iv: string; data: string }[]); r.onerror = () => reject(r.error);
    });
    const items = await Promise.all(rows.map((x) => unseal<QueueItem>(x)));
    return items.sort((a, b) => a.created_at.localeCompare(b.created_at));
  } finally { db.close(); }
}
export async function removeItem(id: string): Promise<void> {
  await tx("items", "readwrite", (s) => s.delete(id));
  await setCount();
}
export async function saveSnapshot(snap: Snapshot): Promise<void> {
  const box = await seal(snap);
  await tx("snapshot", "readwrite", (s) => s.put(box, "current"));
}
export async function loadSnapshot(): Promise<Snapshot | null> {
  const box = await tx<{ iv: string; data: string } | undefined>("snapshot", "readonly", (s) => s.get("current"));
  return box ? unseal<Snapshot>(box) : null;
}
