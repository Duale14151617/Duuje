#!/usr/bin/env node
// Post-build step for Netlify: writes dist/_redirects and dist/_headers (honoured by git deploys AND drag-and-drop).
//   API_ORIGIN=https://api.example.org npm run build:netlify   -> /api/* is proxied to that backend (same-origin for the browser)
//   (API_ORIGIN unset)                                         -> frontend only: the app shows "Cannot reach the server"
//   node scripts/netlify-dist.mjs --demo                       -> standalone demo build (built-in sample data, no API at all)
// DIST_DIR=/path overrides the folder to process (default: ../dist).
// The CSP hash for the inline theme script is computed from the BUILT index.html, so editing that script never breaks the CSP.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const demo = process.argv.includes("--demo");
const dist = process.env.DIST_DIR ?? join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const indexPath = join(dist, "index.html");
if (!existsSync(indexPath)) { console.error("dist/index.html not found: run `npm run build` first."); process.exit(1); }

const raw = demo ? "" : (process.env.API_ORIGIN ?? "").trim();
if (demo && process.env.API_ORIGIN) console.warn("Demo build: API_ORIGIN is ignored (the demo never calls an API).");
let api = "";
if (raw) {
  let u;
  try { u = new URL(raw); } catch { u = null; }
  if (!u || u.protocol !== "https:" || u.pathname !== "/" || u.search || u.hash || u.username) {
    console.error(`API_ORIGIN must be a bare https origin such as https://api.example.org (got "${raw}").`);
    process.exit(1);
  }
  api = u.origin;
}

const html = readFileSync(indexPath, "utf8");
const hashes = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map((m) => `'sha256-${createHash("sha256").update(m[1]).digest("base64")}'`);

const csp = [
  "default-src 'self'",
  `script-src 'self' ${hashes.join(" ")}`.trim(),
  "style-src 'self'",
  "style-src-attr 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

// Order matters: the API rule must come before the SPA fallback.
const redirects = [
  ...(api ? [`/api/*  ${api}/api/:splat  200!`] : []),
  "/*  /index.html  200",
  "",
].join("\n");

const headers = `/*
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: same-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
  Content-Security-Policy: ${csp}
/index.html
  Cache-Control: no-cache
/sw.js
  Cache-Control: no-cache
/manifest.webmanifest
  Content-Type: application/manifest+json
  Cache-Control: no-cache
/offline.html
  Cache-Control: no-cache
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/api/*
  Cache-Control: no-store
`;

writeFileSync(join(dist, "_redirects"), redirects);
writeFileSync(join(dist, "_headers"), headers);
console.log(demo
  ? "Netlify files written for the standalone DEMO build (sample data, nothing is saved)."
  : api
    ? `Netlify files written. /api/* is proxied to ${api}.`
    : "Netlify files written in FRONTEND-ONLY mode (no API_ORIGIN): sign-in will report that the server cannot be reached.");
console.log(`Inline scripts allowed by hash: ${hashes.length}.`);
