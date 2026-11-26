"""Official Puntland Army rank catalogue (Addendum to 1.3, version 1.3.1).

The first 16 names and their order were supplied by the institution and are stored exactly as supplied. They are stored
in the database (table `ranks`), so authorised administrators can edit them without touching code; this module is only
the initial content. No translations are invented: the supplied name is used for both language fields until the
institution supplies verified wording. The bracketed "(General)" and "(Marshall)" are part of the supplied names.
"""
import re

OFFICIAL_ARMY_RANKS = [
    "Dable", "Alifle", "2 Alifle", "Saddex Alifle", "Isbatoore", "Laba Xarigle", "Saddex Xarigle", "Xidigle",
    "Laba Xidigle", "Captain", "Gaashanle", "Gaashanle dhexe", "Gaashanle sare", "Sarreye Guuto (General)",
    "Sarreye Gaas", "Sarreye Guud (Marshall)",
    "Commander of the Puntland Defense Forces",  # senior military command appointment
    "President / Commander-in-Chief",  # highest constitutional authority
]
CODE_PREFIX = "PA-"  # internal identifier (Puntland Army, position in the order); editable, not an official code
PROVISIONAL_CODE = re.compile(r"^[EWO]-\d{1,2}$")  # the provisional US-style codes seeded in 1.0-1.3


def code_for(position):
    return f"{CODE_PREFIX}{position:02d}"


def apply_official_ranks(Rank, Personnel, army, now):
    """Idempotent. Adds the 18 ranks (approved, because supplied as official) and retires the provisional ones.

    Provisional US-style ranks that nobody holds are removed; ones that people hold are kept but deactivated, so no
    personnel record is orphaned or silently re-ranked. Returns (created, removed, deactivated).
    """
    created = removed = deactivated = 0
    for position, name in enumerate(OFFICIAL_ARMY_RANKS, start=1):
        rank, was_created = Rank.objects.get_or_create(
            branch=army, code=code_for(position),
            defaults={"category": "unspecified", "name_en": name, "name_so": name, "sort_order": position,
                      "approval_status": "approved", "approved_at": now, "active": True})
        created += was_created
    for old in Rank.objects.filter(branch=army):
        if not PROVISIONAL_CODE.match(old.code):
            continue
        if Personnel.objects.filter(rank=old).exists():
            if old.active:
                Rank.objects.filter(pk=old.pk).update(active=False, sort_order=1000 + old.sort_order)
                deactivated += 1
        elif old.approval_status == "draft":
            old.delete()
            removed += 1
        elif old.active:
            Rank.objects.filter(pk=old.pk).update(active=False, sort_order=1000 + old.sort_order)
            deactivated += 1
    return created, removed, deactivated
