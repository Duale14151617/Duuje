# Test plan and evidence log (Version 1.4)

Status values: **NOT RUN** (default), PASS, FAIL (with ticket). Fill this in as you execute it.

## A. Automated suites
| Check | Command | Status |
|---|---|---|
| Backend tests on SQLite (fast) | `cd backend && DJANGO_DEBUG=1 USE_SQLITE=1 python manage.py test apps` | NOT RUN |
| Backend tests on PostgreSQL (includes triggers + real concurrency) | `DJANGO_DEBUG=1 POSTGRES_PASSWORD=... python manage.py test apps` | NOT RUN |
| Models match migrations | included in the suite (`test_models_and_migrations_agree`) | NOT RUN |
| Deployment checks | `python manage.py check --deploy --fail-level ERROR` (production-shaped env) | NOT RUN |
| Frontend typecheck / lint / unit | `cd frontend && npm ci && npm run typecheck && npm run lint && npm test` | NOT RUN |
| Dependency audit | `pip-audit -r backend/requirements.txt`; `npm audit --omit=dev` | NOT RUN |
| Accessibility + layout smoke (desktop, Pixel 5, 360px phone; EN and SO) | `npm run e2e` against a running stack | NOT RUN |

## B. Operations rehearsals (cannot be done by code alone)
| Check | How | Status |
|---|---|---|
| Encrypted backup | `ops/backup.sh`; confirm archive + checksum, copy off-host | NOT RUN |
| **Restore test** | `ops/restore_test.sh <archive>`; log it in `docs/RUNBOOK.md` | NOT RUN |
| Migration round-trip | `ops/migration_roundtrip.sh` on a scratch database | NOT RUN |
| Monitoring + alert path | trip `security_report` thresholds on staging; confirm a human is paged | NOT RUN |
| Incident drill | walk the "account compromise" playbook with the owner and operator | NOT RUN |

## C. Manual checks
| Area | What to verify | Status |
|---|---|---|
| Android phones | Chrome on a low-end Android 8+ device and a recent one: sign-in, bottom navigation scrolls, forms, date pickers, tables scroll inside their container, no sideways page scroll | NOT RUN |
| Slow networks | throttle to slow 3G: loading states, errors readable, retry works | NOT RUN |
| Screen reader | TalkBack on Android and NVDA/VoiceOver on desktop: labels, errors announced (`role="alert"`), focus order | NOT RUN |
| Keyboard only | every flow reachable and focus visible | NOT RUN |
| Zoom / text size | 200% zoom and large system font; no clipped controls | NOT RUN |
| Contrast | light and dark themes meet WCAG AA | NOT RUN |
| Somali review | a qualified translator reviews every Somali string, including errors and role names | NOT RUN |
| Session behaviour | idle timeout, absolute timeout, sign-out on another device after password change | NOT RUN |

## D. Performance (targets are proposals for the institution to confirm)
| Scenario | Proposed target | How to measure | Status |
|---|---|---|---|
| Paginated lists at 100k personnel, 1M ledger rows | p95 < 500 ms at 50 concurrent users | load tool (k6/Locust) against staging with synthetic volume; check `EXPLAIN` on slow queries | NOT RUN |
| Login | p95 < 1 s (password hashing dominates) | same | NOT RUN |
| Concurrent stock issue | no overdraw, no deadlock at 50 parallel clients | extend `test_concurrency_pg.py` or load tool | NOT RUN |
| CSV import 1,000 rows | < 10 s | upload on staging | NOT RUN |

## E. Independent review (see `docs/SECURITY.md`)
Scope, rules of engagement, and a named independent reviewer must be agreed by the institution. Critical and high
findings are fixed and re-tested before any production use. Status: **NOT STARTED**.
