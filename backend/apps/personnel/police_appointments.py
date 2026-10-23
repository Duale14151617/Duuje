"""Police command appointments: Chief of Police (one per regional Police command) and Station Commander (one per Police station).

Appointment titles are data (AppointmentType), so an administrator can rename them; the codes below are what the rules key on.
Somali names are left blank: none were supplied, and none are invented. The titles are working labels to confirm with the Police.

Chain: Region Police command -> Chief of Police -> Station Commander of each station under that command.
"""
CHIEF = "CHIEF_OF_POLICE"
STATION_LEAD = "STATION_COMMANDER"

# code, English working label, level of the unit the appointment belongs to, one holder per unit
POLICE_APPOINTMENT_TYPES = [
    (CHIEF, "Chief of Police", "branch_command", True),
    (STATION_LEAD, "Station Commander", "station", True),
]
LEVEL_FOR = {code: level for code, _, level, _ in POLICE_APPOINTMENT_TYPES}


def ensure_types(AppointmentType):
    """Idempotent; never overwrites an administrator's edits. Returns how many were created."""
    n = 0
    for code, en, _level, exclusive in POLICE_APPOINTMENT_TYPES:
        _, created = AppointmentType.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": "", "exclusive": exclusive})
        n += created
    return n


def unit_fits(code, unit):
    """True when `unit` is the right kind of Police unit for this appointment type (or the type is not a Police one)."""
    level = LEVEL_FOR.get(code)
    if level is None:
        return True
    if unit.level != level:
        return False
    if level == "branch_command":
        return unit.branch is not None and unit.branch.code == "POLICE"
    return unit.parent is not None and unit.parent.branch is not None and unit.parent.branch.code == "POLICE"
