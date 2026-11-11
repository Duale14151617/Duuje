"""Suggest the unit a new person fits, from their specialty. Advice only: nothing here blocks an assignment.

A unit has a *function* when it is a specialist unit (medical, finance, transport ...). The function is read from the unit's
type, then from words in its code and names, and it is inherited by the units below it (a team under the Medical Directorate
is a medical unit). A unit with no function is a general unit.

  * a person whose specialty matches a unit's function fits that unit;
  * infantry (general duty) fit the general line units (Guuto, Urur, Koox ...) and the Forces Directorate;
  * everything else is a mismatch: a medic is never suggested a general unit, and nobody is suggested another trade's unit.
"""
from apps.organization.models import OrganizationalUnit

# code -> (English, Somali). The Somali labels are working translations to confirm with the army.
SPECIALTIES = {
    "infantry": ("Infantry / general duty", "Ciidan guud"),
    "medical": ("Medical", "Caafimaad"),
    "transport": ("Transport / driver", "Gaadiid"),
    "communications": ("Communications / signals", "Isgaarsiin"),
    "finance": ("Finance / accounts", "Maaliyad"),
    "supply": ("Supply / logistics", "Saad iyo taakulo"),
    "operations": ("Operations / planning", "Howlgelin"),
    "administration": ("Administration / clerk", "Xafiis iyo maamul"),
}

UNIT_TYPE_FUNCTION = {
    "HEALTH_DEPT": "medical", "KOOX_MED": "medical", "URUR_CAAFIMAAD": "medical",
    "FINANCE_DEPT": "finance", "URUR_LACAG": "finance",
    "URUR_SAAD": "supply", "URUR_HOWLGELIN": "operations", "URUR_XAFIIS": "administration",
}
# Words looked for in "code name_en name_so" (lower case). The first function that matches wins, so the order matters.
KEYWORDS = [
    ("medical", ("caafimaad", "medical", "health", "clinic", "hospital")),
    ("finance", ("maaliy", "finance")),
    ("transport", ("gaadiid", "transport")),
    ("communications", ("isgaarsiin", "communication", "signal")),
    ("supply", ("saad", "supply", "logistic", "taakul", "support directorate", "quartermaster")),
    ("operations", ("howlgelin", "operations")),
    ("administration", ("xafiis", "admin")),
    ("infantry", ("hogganka ciidanka", "forces directorate")),
]
LINE_TYPES = {"GAAS", "GUUTO", "URUR", "HORIN", "KOOX", "UNUG"}  # fighting-force units: where general-duty soldiers belong
MAX_SUGGESTIONS = 8


def _own_function(row):
    function = UNIT_TYPE_FUNCTION.get(row["unit_type__code"])
    if function:
        return function
    text = f'{row["code"]} {row["name_en"]} {row["name_so"]}'.lower()
    for function, words in KEYWORDS:
        if any(w in text for w in words):
            return function
    return None


def unit_functions():
    """{unit id: function or None} for every active unit; a unit with no function of its own inherits its parent's."""
    rows = {r["id"]: r for r in OrganizationalUnit.objects.filter(active=True)
            .values("id", "parent_id", "code", "name_en", "name_so", "unit_type__code")}
    memo = {}

    def resolve(uid):
        if uid in memo:
            return memo[uid]
        row = rows.get(uid)
        memo[uid] = None  # guards against a cycle
        if row is not None:
            memo[uid] = _own_function(row) or (resolve(row["parent_id"]) if row["parent_id"] else None)
        return memo[uid]

    return {uid: resolve(uid) for uid in rows}, rows


def fit(specialty, function, unit_type_code):
    """'match' (suggest it), 'general' (a general unit, fine for nobody in particular) or 'mismatch'."""
    if function == specialty:
        return "match"
    if function is None:
        if specialty == "infantry" and unit_type_code in LINE_TYPES:
            return "match"
        return "general"
    return "mismatch"


def suggest(candidates, specialty, under=None, limit=MAX_SUGGESTIONS):
    """Units from `candidates` (a queryset the caller is allowed to use) that fit `specialty`, best first."""
    functions, rows = unit_functions()
    out = []
    for unit in candidates.filter(level__in=["branch_command", "unit"], active=True).select_related("unit_type"):
        if under is not None and not unit.path.startswith(under.path):
            continue
        type_code = unit.unit_type.code if unit.unit_type_id else None
        if fit(specialty, functions.get(unit.pk), type_code) != "match":
            continue
        # specialist matches (a medical unit for a medic) come before general-duty line units; then nearest the top of the tree
        out.append((0 if functions.get(unit.pk) == specialty else 1, unit.path.count("/"), unit.code, unit))
    out.sort(key=lambda t: t[:3])
    return [t[3] for t in out[:limit]]


def judge(unit, specialty):
    """How well one unit suits `specialty`: {'fit': ..., 'function': ...}."""
    functions, _ = unit_functions()
    function = functions.get(unit.pk)
    type_code = unit.unit_type.code if unit.unit_type_id else None
    return {"fit": fit(specialty, function, type_code), "function": function}
