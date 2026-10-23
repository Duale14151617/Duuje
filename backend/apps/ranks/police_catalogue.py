"""Police rank catalogue: THE SAME RANKING AS THE ARMY (instruction of 2026-10-23).

The Police use the 18 official Puntland Army ranks, in the same order, approved as supplied. They are separate rows in the `ranks` table
(own branch, own codes `PL-01`..`PL-18`), so the Police list can later be edited, reordered or swapped without touching the Army's.
Names are stored in both language fields exactly as for the Army. Nothing here is a constraint: authorised administrators change
names, categories and order on the Ranks page (or through the API), including swapping two ranks' positions.

Replaced: the earlier DRAFT catalogue taken from Article 23 of Law No. 2 of 23 December 1972 (codes `PP-01`..`PP-15`). Those rows are
retired when they are still exactly as seeded: removed if nobody references them, otherwise kept but deactivated (so no personnel record
is orphaned). Rows an administrator has edited are left alone. The old list is kept below only to recognise those rows and for the
`approve_police_ranks` command, which now only matters for any Article 23 rows still in draft.
"""
from .catalogue import OFFICIAL_ARMY_RANKS

CODE_PREFIX = "PL-"  # internal identifier (Puntland Police, position in the order); editable, not an official code
LEGACY_PREFIX = "PP-"  # the retired Article 23 draft catalogue
# (category, name) - senior -> junior, as in Article 23
ARTICLE_23 = [
    ("senior_officer", "Colonel"), ("senior_officer", "Lieutenant Colonel"), ("senior_officer", "Major"),
    ("junior_officer", "Captain"), ("junior_officer", "Lieutenant"), ("junior_officer", "Second Lieutenant"),
    ("inspector", "Chief Inspector"), ("inspector", "Inspector"), ("inspector", "Sub-Inspector"),
    ("nco", "First Sergeant"), ("nco", "Sergeant"), ("nco", "Cadet Officer"),
    ("askari", "First Askari"), ("askari", "Askari"), ("askari", "Recruit"),
]


def apply_police_ranks(Rank, police, now=None):
    """Idempotent; never overwrites administrator edits or approvals. Adds the 18 ranks (approved, same as the Army) and retires the
    untouched Article 23 draft rows. Returns the number created."""
    from django.db.models import ProtectedError
    from django.utils import timezone
    now = now or timezone.now()
    created = 0
    for position, name in enumerate(OFFICIAL_ARMY_RANKS, start=1):
        _, was_created = Rank.objects.get_or_create(
            branch=police, code=f"{CODE_PREFIX}{position:02d}",
            defaults={"category": "unspecified", "name_en": name, "name_so": name, "sort_order": position,
                      "approval_status": "approved", "approved_at": now, "active": True})
        created += was_created
    law = set(ARTICLE_23)
    for old in Rank.objects.filter(branch=police, code__startswith=LEGACY_PREFIX):
        if (old.category, old.name_en) not in law:
            continue  # edited by an administrator: leave it alone
        if old.approval_status == "draft":
            try:
                old.delete()
                continue
            except ProtectedError:
                pass
        if old.active:
            Rank.objects.filter(pk=old.pk).update(active=False, sort_order=1000 + old.sort_order)
    return created
