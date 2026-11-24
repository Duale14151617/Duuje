/* POLICE HQ service worker.
   SECURITY: this system holds sensitive personnel records, so the worker NEVER caches pages, API responses or
   anything user-specific. It only caches the public app files (hashed build assets, icons, offline screen).
   When the network is down, page loads show a plain offline screen. Bump VERSION to refresh all devices.
   v2 (offline desk): the generic app shell (index.html) is also kept so the offline desk can open with no signal. It is the same
   file for every user and holds no personal data; the records an officer enters offline are kept separately in an encrypted vault. */
const VERSION = "policehq-v3";
const SHELL = "/__shell__";
const PRECACHE = ["/offline.html", "/offline.css", "/offline.js", "/icon-192.png", "/icon-512.png", "/favicon-32.png", "/favicon.ico", "/puntland-flag-logo.png"];

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

  // Page loads: network first. A good HTML answer refreshes the saved shell; with no network the shell opens the app
  // (the offline desk) and, if there is no shell yet, the plain offline screen.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).then((res) => {
        const type = res.headers.get("content-type") || "";
        if (res.ok && type.includes("text/html") && !res.redirected && !url.pathname.startsWith("/admin")) {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(SHELL, copy));
        }
        return res;
      }).catch(() => caches.match(SHELL).then((hit) => hit || caches.match("/offline.html")))
    );
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
