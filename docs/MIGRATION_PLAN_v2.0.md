# Migration plan, deployment and rollback — 2.0.0 (from 1.4.0)

Properties: migrations only **create** objects (tables `integration_clients`, `integration_calls`, index, one append-only trigger). No existing table or column is altered. Verified structurally by `apps/core/tests/test_v2_compatibility.py` (written; not executed by the author).

## Before
1. Take and verify a backup: `ops/backup.sh`; confirm a restore with `ops/restore_test.sh` on a non-production host if you have not done so recently.
2. On a **copy** of production (or staging), run the whole procedure below first.
3. Keep 1.4.0 artefacts available for rollback.

## Upgrade
1. Stop or drain the application (a short maintenance window is enough; the migrations are quick).
2. Deploy the 2.0.0 backend and frontend build.
3. `cd backend && python manage.py migrate` (applies `organization.0004` and `integrations.0001`, `integrations.0002`; all create new tables only).
4. `python manage.py seed_reference_data` — registers the five new permissions, creates the `structure_approver` role, gives `analytics.view` to `hq_reporting`, `regional_chief`, `branch_admin` and `org.structure_propose` to `hq_admin`. Then assign the *Structure approver* role (HQ) to a person who is **not** the one who will propose changes. Idempotent; it re-syncs system roles as in every release.
5. **Behaviour change to announce:** with `STRUCTURE_CHANGES_REQUIRE_APPROVAL` on (default) the Structure page's direct edit of levels returns *approval_required*; use *Structure changes* instead. Set it to `0` only if you must keep the 1.4 behaviour during transition.
6. Settings: leave `INTEGRATIONS_ENABLED=0` unless an integration is approved. Other new variables are optional (see `.env.example`).
7. `python manage.py check --deploy`, then smoke test: sign in; open Analytics as a regional chief (sees only the region); `/api/v1/health/ready/`.
8. Run the full test suite on the staging copy: `python manage.py test apps --noinput`.

## Enabling an integration (separately, after approval)
Set `INTEGRATIONS_ENABLED=1`, restart; an HQ administrator who holds the relevant data permissions creates the key in *Integrations*; hand the key over through an approved channel; schedule `python manage.py integration_report` (exit code 2 = attention needed).

## Rollback
- **Fastest, no data change:** set `INTEGRATIONS_ENABLED=0` (external endpoints answer 404; keys can still be revoked in the UI/API).
- **Code rollback, keep tables:** redeploy 1.4.0 and run its `seed_reference_data` (removes the new grants). The two extra tables are unused by 1.4.0 and harmless.
- **Code rollback, remove tables:** *with 2.0 code still deployed* run `python manage.py migrate organization 0003` and `python manage.py migrate integrations zero` (drops the proposals table, then the trigger and integration tables; this discards structure proposals, integration clients and their call log; applied level changes stay, they are ordinary data), then deploy 1.4.0.
- **Worst case:** restore the pre-upgrade backup (`ops/restore_test.sh` documents the restore) and deploy 1.4.0.
