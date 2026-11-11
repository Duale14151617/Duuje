# Monitoring and alerting

Scrape `api:8080/metrics` with `Authorization: Bearer $Metrics__Token` (the endpoint does not exist without a token). Probe `/health/live` (process) and `/health/ready` (database, pending migrations, file storage). Every response carries `X-Correlation-Id`, which is also the correlation id on audit rows and in logs: ask users for it.

Ship container logs to a central store. Logs must not contain secrets, tokens, document contents or message bodies; the application does not log them — keep it that way in code review.

| Alert | Condition (starting values — tune on staging) | First action |
|---|---|---|
| API down | `/health/ready` failing 2 min | restart, check DB, see incident-response.md |
| Error rate | `rate(duale_http_responses_5xx_total[5m]) / rate(duale_http_requests_total[5m]) > 2%` | logs by correlation id; roll back if release-related |
| Latency | p95 of `duale_http_request_seconds` > 500 ms for 10 min | DB load, slow queries |
| Rate limiting | `duale_http_rate_limited_total` rising fast | abuse or a client loop; identify the user from logs |
| Notification backlog | `duale_notification_deliveries_pending` > 500 or `duale_notifications_not_fanned_out` > 200 for 10 min | worker running? provider outage? |
| Dead notifications | `duale_notification_deliveries_dead` increasing | provider config/address problems; retry via `/platform/notifications/deliveries/{id}/retry` |
| Outbox backlog | `duale_outbox_pending` growing for 10 min, or `duale_outbox_dead` > 0 | no publisher registered yet (expected until a consumer exists), consumer down? retry dead rows via `/platform/outbox/{id}/retry` |
| Stuck payments | `duale_payments_initiated_over_24h` > 0 | finance: confirm or fail them |
| Reconciliation lag | `duale_payments_confirmed_unreconciled` growing over days | finance reconciliation backlog |
| Disputes | `duale_disputes_open` > agreed limit | assign a decider |
| Verification queues | `duale_verification_queue_*` older than the agreed SLA | verification officers |
| Integrity | daily `GET /platform/integrity` returns `ok:false` | treat as an incident (possible corruption or a bug) |
| Infrastructure | disk > 80%, DB connections > 80%, backup older than 26 h, certificate expiry < 14 d | per host runbook |

Capacity: API and worker scale horizontally (the worker's reminder keys and delivery unique indexes make parallel instances safe). Queue depth, DB capacity and storage are the first things to watch when scaling.
