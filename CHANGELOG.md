# Changelog

## Unreleased: Police module completion, batch 1
- Disciplinary history and service documents on personnel files (encrypted, audited, append-only / never deleted).
- Cross-service duplicate-identity check (block / flag) and `report_duplicate_identities` command.
- Combined Army + Police report (`reports.combined`).
- Police stations (`station` level) under regional Police commands.
- Police sample data in `seed_test_personnel`.
- Migrations: personnel 0004, organization 0006. Backend tests unrun at time of writing: run the suite before deploying.

## 2.1.2 - Midnight Navy + Gold theme (frontend, colours only)
Replaced the olive/gold palette with Midnight Navy + Muted Gold in the existing token system (`frontend/src/styles.css`), for both light and dark
themes. Colours only: no markup, layout, routing, API, permission, translation or business-logic change; the theme toggle is unchanged. Adds a
brand-token layer, a darker `--gold-strong` for functional gold on light surfaces, a stronger input/secondary-button border (`--control-border`),
semantic info tokens, chart tokens, button hover states and an opt-in `.gold` button. The favicon and the browser `theme-color` now match the
navy header. Version numbers were not changed. See `docs/CHANGE_REPORT_theme_midnight_navy_gold.md` (includes what was and was not verified).
## 2.1.2 (frontend only)
Netlify-ready frontend without the backend: `frontend/netlify.toml`, `npm run build:netlify` (`scripts/netlify-dist.mjs` writes `_redirects`
with an optional `API_ORIGIN` proxy and the SPA fallback, and `_headers` with a strict CSP whose inline-script hash is computed at build time),
`docs/NETLIFY.md`. The API client now treats an HTML or proxy-error response as "server unreachable" instead of silently accepting it as data
(previously a static host with no API made sign-in appear to do nothing); the login page shows that message when the server cannot be reached.
Added the standalone demo build (`npm run build:demo`: built-in sample API in `src/demo/mock.ts`, `.env.demo`, banner; Netlify default). Added client tests, favicon, `robots.txt`/noindex, `.nvmrc`. Fixed the example nginx CSP, which blocked the inline theme script and React's
inline `style` attributes. No backend or API changes.
## 2.1.1 (frontend only)
Ported the demo build's interface into the source: olive/gold palette, KPI dashboard (cards, "Needs attention" list, per-area panels,
activity meter), icon sign-out button, and an optional demo banner (`VITE_DEMO=1`, off by default). Added browser-side PDF export
(`src/lib/pdf.ts`, no new dependencies) for Personnel, Requests and reports, Summaries, Audit log and the Dashboard; the first three
follow the same permission and feature switches as the CSV exports. Personnel import gained a CSV template, instant client-side checks that
mirror the server limits, drag and drop, step indicator and a downloadable problem list. No backend or API changes.
## 2.0.0
Governed structure changes: `StructureChange` proposals with impact report, `org.structure_propose` / `org.structure_approve`, role `structure_approver`, `organization.0004`, page *Structure changes*; direct unit-type edits now need `STRUCTURE_CHANGES_REQUIRE_APPROVAL=0`.
(Hardening within 2.0: keys cannot use `?unit=` unless `INTEGRATION_ALLOW_UNIT_FILTER=1`; `integration_report` flags keys whose creator lost access.)
Institutional expansion, additive only. New `analytics` app (scoped aggregates), new `integrations` app (read-only bearer-key API,
off by default, hashed keys, expiry, rotation, revocation, small-cell withholding, per-key and per-address throttling, append-only
call log, audit), scoped unit tree, permissions `analytics.view` / `integrations.view` / `integrations.manage`, `integration_report`
command, frontend pages and Somali/English strings, compatibility tests against 1.4. Not built: configurable structural levels,
outbound integrations, offline access. See `docs/IMPACT_ASSESSMENT_v2.0.md` and `docs/CHANGE_REPORT_v2.0.0.md`.
## 1.4.0 (addendum merged from 1.3.1)
The 16 official Puntland Army ranks replace the provisional US-style list; organizational template (Taliska Guud ... Unug)
with reference strengths and approved exceptions, specialist designations (Sahan, Sanco) and expected-relationship rules,
Structure page, searchable unit picker, audit events for the new admin operations, and the fix for 404/403 from
`get_object()` ending in a 500. No other 1.4 behaviour changed. See `docs/CHANGE_REPORT_v1.4.0_merge.md`.
## 1.4.0
Security and reliability hardening only (see docs/SECURITY.md): throttle-bypass fix, TOTP replay protection, absolute
session lifetime, one-time password recovery, database append-only triggers, request limits and security headers, log
redaction, `check --deploy` rules, health endpoints, audit-of-audit-reads, backup/restore/migration scripts, runbook,
CI, authorization sweep + cross-region canary tests, migration/performance tests, accessibility e2e scaffolding.
## 1.3.0
Logistics (categories with institutional review, stock lines with an append-only ledger, serialized assets with
unit-level issue/return and custodianship, reconciliation, restricted-equipment workflow, summaries) and Training
(course catalogue, personnel training records with status rules, minimal roster lookup, summaries). Dashboard blocks.
Fixed a latent 1.0 migration mismatch (audit migration listed a manager).
## 1.2.0
Requests, reports and approvals: configurable types, draft/submitted/under-review/approved/rejected/returned/amended
states, immutable revisions, approval history with comments, separation of duties, scoped regional and headquarters
summaries (approved content only), in-app notifications, controlled summary export (off by default), dashboard blocks.
## 1.1.0
Personnel management: records, scoped search/filter/pagination, duplicate detection, effective-dated rank/unit/status
history, transfer and status workflows, safe CSV import (preview then commit), controlled CSV export (off by default).
Also: field-error codes fixed for hand-raised validation errors (affected 1.0 auth/version errors); malformed UUID
filters now return 400.
## 1.0.0
Initial foundation release. See docs/CHANGE_REPORT_v1.0.md.
