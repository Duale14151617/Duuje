"""Cell placement warnings. They only WARN: nobody is ever refused a cell for these reasons.

The rules the administration decides are kept in settings, not in code:
* each cell can be marked "women only", "juveniles only" or "adult men only" (Custody facilities > Cells);
* the age below which a person counts as a juvenile is `DETENTION_JUVENILE_UNDER_AGE`. It is EMPTY by default, so no juvenile rule
  runs until the institution sets the age that applies.
Mixing men and women in one cell is always flagged: it needs no setting."""
from django.conf import settings

from .models import CustodyCell, DetentionRecord

MESSAGES = {
    "cell_reserved_women": "This cell is reserved for women.",
    "cell_reserved_men": "This cell is reserved for adult men.",
    "cell_reserved_juveniles": "This cell is reserved for juveniles.",
    "cell_mixed_sex": "Men and women would be held in the same cell.",
    "cell_mixed_age": "A juvenile and an adult would be held in the same cell.",
}


def juvenile_under():
    raw = getattr(settings, "DETENTION_JUVENILE_UNDER_AGE", None)
    return int(raw) if str(raw or "").strip().isdigit() else None


def _juvenile(age):
    limit = juvenile_under()
    return limit is not None and age is not None and age < limit


def evaluate(sex, age, cell_reserved_for, others):
    """Warning codes for one person in one cell. `others` is a list of (sex, age) of the other people in the cell."""
    codes = []
    juv = _juvenile(age)
    if cell_reserved_for == CustodyCell.ReservedFor.WOMEN and sex != "female":
        codes.append("cell_reserved_women")
    elif cell_reserved_for == CustodyCell.ReservedFor.MEN and (sex != "male" or juv):
        codes.append("cell_reserved_men")
    elif cell_reserved_for == CustodyCell.ReservedFor.JUVENILES and _not_juvenile_or_unchecked(age, juv):
        codes.append("cell_reserved_juveniles")
    if sex in ("male", "female") and any(o_sex in ("male", "female") and o_sex != sex for o_sex, _ in others):
        codes.append("cell_mixed_sex")
    if juvenile_under() is not None and any(_juvenile(o_age) != juv for _, o_age in others if o_age is not None) and age is not None:
        codes.append("cell_mixed_age")
    return codes


def _not_juvenile_or_unchecked(age, juv):
    """For a juveniles-only cell: warn when the person is an adult, or the juvenile age is not configured (the rule cannot be checked)."""
    return juvenile_under() is None or not juv


def warnings_for(sex, age, cell, exclude_pk=None):
    """List of {"code", "message"} for placing someone of this sex and age in `cell` now (None cell: no warnings)."""
    if cell is None:
        return []
    others = [(r.sex, r.age_years) for r in DetentionRecord.objects.filter(cell_ref=cell, status="in_custody").exclude(pk=exclude_pk)]
    return [{"code": c, "message": MESSAGES[c]} for c in evaluate(sex, age, cell.reserved_for, others)]


def flagged_counts(unit_ids):
    """{station id: number of people in custody currently placed against a warning}, for the dashboard."""
    rows = list(DetentionRecord.objects.filter(org_unit_id__in=list(unit_ids), status="in_custody", cell_ref__isnull=False).select_related("cell_ref"))
    by_cell = {}
    for r in rows:
        by_cell.setdefault(r.cell_ref_id, []).append(r)
    out = {}
    for group in by_cell.values():
        for r in group:
            others = [(o.sex, o.age_years) for o in group if o.pk != r.pk]
            if evaluate(r.sex, r.age_years, r.cell_ref.reserved_for, others):
                out[r.org_unit_id] = out.get(r.org_unit_id, 0) + 1
    return out
