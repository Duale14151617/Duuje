"""Police rank catalogue - HISTORICAL BASELINE from Article 23 ("Order of Precedence"), Law No. 2 of 23 December 1972,
Organisation of the Police Force (Somalia).

CHECKED against the supplied copy of the law (Organisation of the Police Force, Somalia, 1972, page 107, Article 23): the 15 names
and their classes below match it exactly, in order. The same copy shows: (a) "General Officers" is listed as the first class with
no individual ranks under it, and Article 3 only speaks of "generals and colonels" without naming any general rank, so the class
stays EMPTY (adding titles such as "Brigadier General" would be a guess); (b) Article 1 defines Non-Commissioned Officers as
Sergeant to 1st Sergeant, yet Article 23 lists "Cadet Officers" under them, so that rank is kept where Article 23 puts it and
flagged for review; (c) the law is a 1972 national law: it is a baseline, not proof of current Puntland Police rules.

Rules followed here:
* Names and classes are exactly those supplied from Article 23, listed senior -> junior in the law.
* The law names a "General Officers" class but the supplied list gives no individual ranks in it. None are invented:
  the class exists as a category, with no ranks, until the institution supplies them.
* Everything is seeded as DRAFT. A draft rank cannot be assigned to anyone (the existing rule), so an authorised
  administrator must review and approve each entry against CURRENT Puntland Police rules before use.
* No Somali wording has been verified, so the English name is stored in both language fields (same convention as the Army
  catalogue); replace it through the rank editor once verified.
* "Cadet Officer" is listed in the NCO class in the supplied text (shown there as "Cadet Officer(s)"); kept as supplied
  and flagged for review.
* Stored in the `ranks` table, so ranks, order, labels and class stay editable without code changes. Kept separate from
  Army ranks (own branch, own codes) even where titles overlap.
"""

CODE_PREFIX = "PP-"  # internal identifier (Puntland Police, position junior -> senior); editable, not an official code
# (category, name) - senior -> junior, as in Article 23
ARTICLE_23 = [
    ("senior_officer", "Colonel"), ("senior_officer", "Lieutenant Colonel"), ("senior_officer", "Major"),
    ("junior_officer", "Captain"), ("junior_officer", "Lieutenant"), ("junior_officer", "Second Lieutenant"),
    ("inspector", "Chief Inspector"), ("inspector", "Inspector"), ("inspector", "Sub-Inspector"),
    ("nco", "First Sergeant"), ("nco", "Sergeant"), ("nco", "Cadet Officer"),
    ("askari", "First Askari"), ("askari", "Askari"), ("askari", "Recruit"),
]


def apply_police_ranks(Rank, police, now=None):
    """Idempotent; never overwrites administrator edits or approvals. Returns the number created."""
    created = 0
    junior_to_senior = list(reversed(ARTICLE_23))  # Army convention: lowest sort_order = most junior
    for position, (category, name) in enumerate(junior_to_senior, start=1):
        _, was_created = Rank.objects.get_or_create(
            branch=police, code=f"{CODE_PREFIX}{position:02d}",
            defaults={"category": category, "name_en": name, "name_so": name, "sort_order": position,
                      "approval_status": "draft", "active": True})
        created += was_created
    return created
