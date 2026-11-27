"""Email alerts for important events: a vehicle crossing a zone boundary, a weapon reported lost or missing, a GPS tracker that goes
silent, and a death report. They reach people who are not signed in.

Who is told: only people who switched that kind of alert on (Account page; see AlertPreference) AND who may see the unit where it
happened, with an active account and a verified email. The choice never widens what a person may know.

What the email says: what happened, where (the unit) and when, with a link to the app. No names, service numbers or phone numbers; a
weapon's serial number and a vehicle's ID and plate are included because the commander needs them to act and they are equipment,
not personal data.

An alert never raises and never blocks the action that caused it: the mail is sent after the surrounding transaction commits, and a
failure is only logged.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts import scope
from apps.accounts.models import User
from apps.core.mailer import send_background

from .models import AlertLog, AlertPreference

log = logging.getLogger("armyhq.alerts")

# kind -> (permission needed over the unit, title shown on the Account page)
KINDS = {
    "zone": ("vehicles.view", "A vehicle crosses a zone boundary"),
    "weapon_lost": ("weapons.view", "A weapon is reported lost or missing"),
    "tracker_silent": ("vehicles.view", "A vehicle's GPS tracker stops reporting"),
    "death_report": ("personnel.view", "A death is reported for a soldier"),
}


def enabled():
    return getattr(settings, "EVENT_ALERTS_ENABLED", True)


def available_kinds(user):
    """The kinds this person could ever be told about: those whose permission they hold somewhere."""
    held = set()
    for a in scope.assignments(user):
        held |= set(a.perm_codes)
    return [k for k, (perm, _t) in KINDS.items() if perm in held]


def wanted_kinds(user):
    return set(AlertPreference.objects.filter(user=user).values_list("kind", flat=True))


def set_kinds(user, kinds):
    """Make `kinds` exactly the set this person receives (only kinds they may have)."""
    allowed = set(available_kinds(user))
    chosen = {k for k in kinds if k in allowed}
    with transaction.atomic():
        AlertPreference.objects.filter(user=user).exclude(kind__in=chosen).delete()
        have = wanted_kinds(user)
        AlertPreference.objects.bulk_create([AlertPreference(user=user, kind=k) for k in chosen - have])
    return chosen


def recipients(kind, unit):
    perm = KINDS[kind][0]
    ids = AlertPreference.objects.filter(kind=kind).values("user_id")
    users = User.objects.filter(pk__in=ids, is_active=True, email_verified_at__isnull=False).exclude(email="")
    return [u for u in users if scope.can(u, perm, unit=unit)]


def _deliver(kind, unit_id, subject, lines, key):
    try:
        from apps.organization.models import OrganizationalUnit
        unit = OrganizationalUnit.objects.get(pk=unit_id)
        if key:
            try:
                with transaction.atomic():
                    entry = AlertLog.objects.create(kind=kind, key=key[:120])
            except IntegrityError:
                return 0  # this exact alert was already sent
        people = recipients(kind, unit)
        if key:
            if people:
                AlertLog.objects.filter(pk=entry.pk).update(recipients=len(people))
            else:
                entry.delete()  # nobody to tell yet: leave it unsent so a later opt-in still hears about a lasting condition
        base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
        prefix = getattr(settings, "ISSUANCE_REF_PREFIX", "PDF")
        body = "\n".join([*lines, "", f"Unit: {unit.name_en}", f"Time (UTC): {timezone.now():%Y-%m-%d %H:%M}",
                          f"Open the app: {base}/" if base else "", "",
                          "You receive this because you switched on this alert on your Account page. You can switch it off there."]).strip() + "\n"
        for u in people:
            send_background(u.email, f"[{prefix}] Alert: {subject}", body)
        return len(people)
    except Exception:
        log.exception("event alert could not be prepared")
        return 0


def alert(kind, unit, subject, lines, key=None):
    """Queue one alert for after the current transaction commits. Never raises."""
    try:
        if not enabled() or kind not in KINDS or unit is None:
            return
        unit_id = unit.pk if hasattr(unit, "pk") else unit
        transaction.on_commit(lambda: _deliver(kind, unit_id, subject, lines, key))
    except Exception:
        log.warning("event alert could not be queued")


# ---- the four events ----------------------------------------------------------------------------------------------------------
def zone_event(event, fence, vehicle):
    word = "entered" if event.kind == "enter" else "left"
    plate = f" ({vehicle.plate})" if vehicle.plate else ""
    alert("zone", vehicle.org_unit, f"Vehicle {vehicle.vehicle_id} {word} zone {fence.name}",
          [f"Vehicle {vehicle.vehicle_id}{plate} {word} the zone \"{fence.name}\".",
           f"Position recorded at {event.occurred_at:%Y-%m-%d %H:%M} UTC."])


def weapon_reported(asset, action):
    """Call after an asset was marked missing or lost; does nothing for assets that are not weapons."""
    if action not in ("missing", "lost"):
        return
    try:
        if not hasattr(asset, "weapon"):
            return
        w = asset.weapon
        what = f"{w.weapon_type}" + (f", {w.make_model}" if w.make_model else "")
        alert("weapon_lost", asset.org_unit, f"Weapon reported {action}",
              [f"A weapon was reported {action}.", f"Weapon: {what}", f"Serial number: {asset.identifier}",
               "Open the weapon register to see the history and the custody that was closed."])
    except Exception:
        log.warning("weapon alert could not be prepared")


def death_reported(person, record):
    alert("death_report", person.org_unit, "Death reported for a soldier",
          [f"A death was reported for a soldier of this unit (date of death {record.date_of_death}).",
           "The report waits for a second officer to confirm it. Open the personnel record to review the evidence."])


def check_silent_trackers(hours=None, limit=100):
    """Alert once for each active GPS tracker that has not reported for `hours` (default: the app's silent-vehicle limit). Called by the
    outside scheduler (schedules/run-due/) or the send_silent_alerts command. Vehicles in the workshop or decommissioned are skipped,
    because silence is expected there. Returns how many alerts were sent."""
    from django.db.models import Q
    from apps.vehicles.models import Vehicle, VehicleTracker
    from apps.vehicles.tracking import STALE_HOURS
    if not enabled():
        return 0
    cutoff = timezone.now() - timedelta(hours=hours or STALE_HOURS)
    rows = (VehicleTracker.objects.filter(active=True).exclude(vehicle__status__in=Vehicle.UNAVAILABLE)
            .filter(Q(last_seen_at__lt=cutoff) | Q(last_seen_at__isnull=True, created_at__lt=cutoff))
            .select_related("vehicle__org_unit").order_by("last_seen_at")[:limit])
    n = 0
    for t in rows:
        since = t.last_seen_at or t.created_at
        v = t.vehicle
        plate = f" ({v.plate})" if v.plate else ""
        seen = f"last heard from at {t.last_seen_at:%Y-%m-%d %H:%M} UTC" if t.last_seen_at else "has never reported"
        # one alert per silent spell: a new spell (the tracker reported, then went quiet again) has a new last-seen time
        if _deliver("tracker_silent", v.org_unit_id, f"Tracker silent on vehicle {v.vehicle_id}",
                    [f"The GPS tracker on vehicle {v.vehicle_id}{plate} {seen}.", "Check the device, its power and its signal."],
                    key=f"{t.pk}:{since:%Y%m%d%H%M%S}"):
            n += 1
    return n
