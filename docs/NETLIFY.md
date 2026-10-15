# Deploying the frontend on Netlify (no backend)

Netlify hosts only the static single-page app. The Django API and PostgreSQL are **not** part of it. Synthetic data only;
see `LIMITATIONS.md` before any real use.

## Standalone demo (default): `npm run build:demo`
Builds the app with `VITE_DEMO=1` (`.env.demo`). The API client then answers from an in-memory sample data set
(`src/demo/mock.ts`) instead of calling a server: any username and password signs in, every page is populated, edits work
until you reload, nothing is saved or sent anywhere, and a banner says so. `netlify.toml` uses this command by default, and
`npm run build:demo` followed by dragging `frontend/dist` onto Netlify's *Deploy manually* page gives the same result.
`src/demo/mock.ts` was reconstructed from the compiled demo build (identifiers are short, type checks are off for that one file).
The sections below cover deploying against a real backend.

## What the build does
`npm run build:netlify` = `npm run build` (typecheck + Vite) + `scripts/netlify-dist.mjs`, which writes into `dist/`:
- `_redirects`: optional `/api/*` proxy to your backend, then the SPA fallback (`/*` to `/index.html`, so `/reset`, deep links and reloads work).
- `_headers`: HSTS, nosniff, frame denial, referrer/permissions policies and a strict CSP. The CSP hash for the small inline
  theme script is computed from the built `index.html`, so editing that script cannot silently break the policy.
- `public/` adds `robots.txt` (disallow all), a `noindex` meta tag and a favicon.

## Two modes
| Mode | Set | Result |
|---|---|---|
| Frontend only | nothing | The site loads; sign-in shows "Cannot reach the server" (the app detects that `/api` is not a real API). |
| With a backend | `API_ORIGIN=https://api.example.org` | `/api/*` is proxied, so the browser sees one origin and the session and CSRF cookies keep working. |

`API_ORIGIN` must be a bare `https://host` (no path, no trailing slash); the script refuses anything else.

## Option A: Git deploy (Netlify builds it)
Import the repository, set **Base directory** = `frontend` (leave empty if you push only the frontend package). The build
command and publish directory come from `netlify.toml`. Add `API_ORIGIN` under Site settings > Environment variables if you have a backend.

## Option B: drag and drop
```bash
cd frontend
npm ci
API_ORIGIN=https://api.example.org npm run build:netlify   # omit API_ORIGIN for frontend-only
```
Drag the `frontend/dist` folder onto Netlify's *Deploy manually* page. `_redirects` and `_headers` inside it are honoured.

## Backend settings needed when you use `API_ORIGIN`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-site>.netlify.app` (the browser's Origin is the Netlify site, not the API host).
- `DJANGO_ALLOWED_HOSTS` must contain the backend host; if requests are rejected with `DisallowedHost`, also add the Netlify site host.
- Leave `TRUST_PROXY_HEADERS=0` unless you have verified the proxy chain (see `deploy/nginx.conf.example`); until then per-address
  login throttling will see Netlify's addresses rather than users'.
- The `__Host-` CSRF cookie and `SameSite=Lax` session cookie work because the proxy keeps everything same-origin. Do **not** point
  the browser straight at a different domain: cookies and CSRF would break.
- Netlify rewrite proxies have request-time limits; keep API calls short (the app's own limit is 30 s behind nginx).

## Not verified
This package was prepared without network access, so `npm ci`, the build, lint, vitest and the Netlify behaviour above were not run
by the author (the new client tests were executed only through a small stand-in for vitest). Run `npm run typecheck && npm run lint && npm test`
and open the deploy preview before relying on it.
