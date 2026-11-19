# Installable app (PWA)

ARMY HQ can be installed on a phone or computer from the browser (Chrome, Edge, Brave: **Install app**; Safari on iPhone: **Share > Add to Home Screen**).
An **Install app** button is also shown on the sign-in page and in the top bar.

## Files
- `frontend/public/manifest.webmanifest`: name, colours and icons (`icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, all made from the Puntland flag image `puntland-flag-hero.png`; the in-app logo is `puntland-flag-logo.png`).
- `frontend/public/sw.js`: service worker. **It never caches pages, API responses or personal data.** It caches only the public app files
  (content-hashed `/assets/*`, icons, offline screen). If the network fails, page loads show `offline.html`.
- `frontend/public/offline.html|css|js`: offline screen. Styles and script are separate files because the Content-Security-Policy forbids inline code.
- `frontend/src/pwa/install.tsx`: service-worker registration and the Install button.

## Requirements
- HTTPS (browsers refuse to install over plain http, except on localhost).
- The service worker is registered in production builds only (not under `npm run dev`).
- `sw.js`, `manifest.webmanifest` and `offline.html` are served with `Cache-Control: no-cache` (WhiteNoise, Netlify `_headers` and the nginx example are updated).

## Updating
Change `VERSION` in `sw.js` to force every device to drop its cached files.
