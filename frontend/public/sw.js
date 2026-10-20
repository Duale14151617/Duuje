/* ARMY HQ service worker.
   SECURITY: this system holds sensitive personnel records, so the worker NEVER caches pages, API responses or
   anything user-specific. It only caches the public app files (hashed build assets, icons, offline screen).
   When the network is down, page loads show a plain offline screen. Bump VERSION to refresh all devices. */
const VERSION = "armyhq-v1";
const PRECACHE = ["/offline.html", "/offline.css", "/offline.js", "/icon-192.png", "/icon-512.png", "/favicon-32.png", "/puntland-flag.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // never touch API traffic

  // Page loads: network only; offline screen if the network fails.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/offline.html")));
    return;
  }

  // Build assets are content-hashed (file name changes with content), so cache-first is safe.
  if (url.pathname.startsWith("/assets/") || PRECACHE.includes(url.pathname)) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res && res.ok && url.pathname.startsWith("/assets/")) {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(req, copy));
        }
        return res;
      }))
    );
  }
});
