# Compatibility with 1.4.0

2.0 only adds. Guarantees and where they are tested (`apps/core/tests/test_v2_compatibility.py`, written but **not executed** by the author):

| Guarantee | Test |
|---|---|
| No role lost any permission; grants added: `analytics.view` (3 roles) and, to `hq_admin` only, `integrations.view/manage` and `org.structure_propose`; the only new role is `structure_approver` | `RoleCompatibilityTests` |
| Administrators still hold no personnel/report/logistics/training/analytics permission | `test_administrators_still_hold_no_data_permissions` |
| Every 1.4 API route is still registered under the same name; only `analytics`, `integrations/clients` and `organization/structure-changes` were added | `RouteCompatibilityTests` |
| `/auth/me/` and `/dashboard/` keep their 1.4 shape (`features.integrations` is a new key; no new dashboard block) | `test_me_and_dashboard_keep_their_v14_shape` |
| Exports and integrations stay off by default | `test_exports_and_integrations_remain_off_by_default` |
| The only migration added to an existing app is `organization.0004` (create-only); new apps only create | `MigrationCompatibilityTests` |
| **Intentional behaviour change:** direct `POST/PATCH` of unit types now returns `409 approval_required` unless `STRUCTURE_CHANGES_REQUIRE_APPROVAL=0`; the three 1.4 tests of that editor run with the gate off | `organization/tests/test_structure.py`, `test_structure_changes.py` |
| All 1.4 tests (authorization sweep, cross-region canaries, hardening, migrations/performance) apply unchanged to the new routes, which the sweep picks up automatically | existing suites |

API versioning: all new endpoints live under `/api/v1/`; no 1.x response field was renamed or removed. Frontend: all existing routes unchanged.
