"""Synthetic Police sample data for every regional command and its two generic stations (Jeelka kowaad / Jeelka labaad).

  python manage.py seed_police_sample                 add the sample people and detainees (idempotent: reruns add nothing twice)
  python manage.py seed_police_sample --officers 4    officers per Koox (default 3)
  python manage.py seed_police_sample --detainees 5   detainees per station (default 4)

Per regional command (9 of them):
  * a regional commander and a deputy (command appointments), plus a head and a staff member for each of the seven standard
    departments (Command and Administration, HR, Medical, Finance, Logistics, Communications, Training);
Per station (2 per region):
  * a station commander and a deputy (command appointments);
  * police officers in Koox 1 and Koox 2, reporting to the station commander;
  * a head of department and a staff member for each of three departments the station establishes (Command and Administration,
    Human Resources, Logistics);
  * detainees in the detention register (most still in custody, one released), each with a custody log, held in the station's jail center;
  * Occurrence Book entries: an entry for every arrest and release, plus a few ordinary ones (complaint, patrol, found property ...).

Everything is clearly fake and removable by hand: people carry the service-number prefix "SMP-", detainees the id reference
"SAMPLE-ID-..." and created_by "sample". NEVER use with real data. Allowed only on a sample deployment (DEBUG, or ARMYHQ_SAMPLE_MODE=1).
Detention rows and appointments are append-only by design, so this command has no delete option.
"""
import os
import random
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.detention import facilities
from apps.detention.models import CustodyFacility, DetentionCounter, DetentionEvent, DetentionRecord
from apps.occurrence.models import OccurrenceEntry
from apps.occurrence.services import next_number
from apps.organization import police_structure as ps, profiles
from apps.organization.models import Department, OrganizationalUnit as OU, UnitDepartment
from apps.personnel import appointments, services as svc
from apps.personnel.management.commands.seed_test_personnel import FAMILY, FEMALE, MALE, _candidates
from apps.personnel.models import AppointmentType, CommandAppointment, Personnel
from apps.ranks.models import Rank

PREFIX = "SMP-"
STATION_DEPARTMENTS = ("COMMAND_ADMIN", "HR", "LOGISTICS")
OFFENCES = [  # fictional, ordinary grounds for holding
    "Theft (sample)", "Disturbing the peace (sample)", "Assault (sample)", "Driving without a licence (sample)",
    "Public disorder (sample)", "Fraud (sample)", "Illegal possession of a weapon (sample)", "Trespass (sample)",
]
OB_ENTRIES = [  # category, summary (all fictional)
    ("complaint", "Complaint of a stolen mobile phone at the market (sample)"), ("patrol", "Foot patrol of the town centre, nothing to report (sample)"),
    ("found_property", "Wallet handed in by a member of the public (sample)"), ("accident", "Minor traffic collision, no injuries (sample)"),
    ("visitor", "Visitor asked about a relative held at the station (sample)"), ("duty_change", "Duty officer handed over to the evening shift (sample)"),
]
PLACES = ["Main market", "Bus stop", "Port road", "Roundabout", "Town centre", "Fish market", "Airport road", "Hospital road"]
CELLS = ["Cell 1", "Cell 2", "Cell 3", "Women's cell"]


def _sample_mode_allowed():
    raw = os.environ.get("ARMYHQ_SAMPLE_MODE") or os.environ.get("ARMYHQ_DEMO_MODE", "0")
    return settings.DEBUG or raw.strip().lower() in ("1", "true", "yes", "on")


class Seeder:
    def __init__(self, officers, detainees, stdout):
        self.officers, self.detainees, self.out = officers, detainees, stdout
        self.today = timezone.localdate()
        self.counter = 0  # running person number: service numbers SMP-0001... never reused
        self.stats = {"people": 0, "appointments": 0, "detainees": 0, "departments": 0, "ob_entries": 0}
        ranks = list(Rank.objects.filter(branch__code=ps.BRANCH_CODE, approval_status=Rank.Approval.APPROVED, active=True)
                     .order_by("sort_order"))
        if len(ranks) < 4:
            raise CommandError("Approved Police ranks are missing. Run `manage.py seed_reference_data` first.")
        n = len(ranks)
        # junior -> senior; pick bands so every role gets a believable rank
        self.junior, self.mid, self.senior, self.top = ranks[:max(1, n // 3)], ranks[n // 3:2 * n // 3], ranks[2 * n // 3:n - 2], ranks[n - 4:n - 1]
        self.senior = self.senior or self.mid
        self.names = iter(_candidates(2500, seed=777))
        self.taken = set(Personnel.objects.values_list("name_key", flat=True))
        self.existing = {s: pk for s, pk in Personnel.objects.filter(service_number__startswith=PREFIX).values_list("service_number", "pk")}
        self.types = {t.code: t for t in AppointmentType.objects.all()}
        self.rng = random.Random(4242)
        self.pending = []

    # ---------------------------------------------------------------------------------------------- people
    def _name(self):
        while True:
            name = next(self.names)
            key = svc.normalize_name(name)
            if key not in self.taken:
                self.taken.add(key)
                return name

    def person(self, unit, rank_pool, department=None, label="Officer"):
        """Create one sample person (or return the one already made for this slot). Slots are numbered in a fixed order."""
        self.counter += 1
        number = f"{PREFIX}{self.counter:04d}"
        if number in self.existing:
            return Personnel.objects.get(pk=self.existing[number]), False
        name = self._name()
        rank = self.rng.choice(rank_pool)
        p = svc.create_personnel(
            None, full_name=name, phone=f"+252906{self.counter:06d}", service_number=number, org_unit=unit, rank=rank,
            status="active", effective_date=self.today - timedelta(days=self.rng.randint(90, 1800)),
            reason=f"Synthetic sample {label.lower()}", department=department)
        self.existing[number] = p.pk
        self.stats["people"] += 1
        return p, True

    def appoint(self, person, unit, type_code, department=None):
        atype = self.types.get(type_code)
        if atype is None or not atype.active:
            return
        if CommandAppointment.objects.filter(org_unit=unit, appointment_type=atype, department=department, ended_at__isnull=True).exists():
            return
        actor = type("Sample", (), {"pk": None, "username": "sample"})()
        appointments.create(actor, person, unit, atype, self.today - timedelta(days=30), authority_ref="Sample order 1/2026", department=department)
        self.stats["appointments"] += 1

    def departments(self, unit, codes):
        """Make sure `unit` has these departments established (regional commands already do; stations get a short list)."""
        found = {}
        for code in codes:
            dept = Department.objects.filter(code=code, active=True).first()
            if dept is None:
                continue
            _, made = UnitDepartment.objects.get_or_create(unit=unit, department=dept)
            self.stats["departments"] += made
            found[code] = dept
        return found

    def head_and_staff(self, unit, codes):
        for code, dept in self.departments(unit, codes).items():
            head, _ = self.person(unit, self.senior, dept, "department head")
            self.appoint(head, unit, "DEPT_HEAD", dept)
            self.person(unit, self.junior + self.mid, dept, "staff member")

    # ------------------------------------------------------------------------------------------ the structure
    def region(self, code, name):
        cmd = OU.objects.filter(code=f"{code}-POL").first()
        if cmd is None:
            self.out.write(f"  skipped {name}: no regional command (run apply_police_structure --apply)")
            return
        chief, _ = self.person(cmd, self.top, label="regional commander")
        self.appoint(chief, cmd, "POLICE_REGION_COMMANDER")
        deputy, _ = self.person(cmd, self.senior, label="deputy regional commander")
        self.appoint(deputy, cmd, "POLICE_REGION_DEPUTY")
        self.head_and_staff(cmd, profiles.STANDARD_DEPARTMENTS)
        for suffix, en, so in ps.STATIONS:
            station = OU.objects.filter(code=f"{code}-POL-{suffix}").first()
            if station is None:
                self.out.write(f"  skipped {name} {en}: station missing (run apply_police_structure --apply)")
                continue
            self.station(station, name)

    def station(self, station, region_name):
        boss, _ = self.person(station, self.senior, label="station commander")
        self.appoint(boss, station, "POLICE_STATION_COMMANDER")
        deputy, _ = self.person(station, self.mid + self.senior[:2], label="deputy station commander")
        self.appoint(deputy, station, "POLICE_STATION_DEPUTY")
        for koox in station.children.filter(unit_type__code="POLICE_KOOX").order_by("code"):
            for _ in range(self.officers):
                officer, created = self.person(koox, self.junior + self.mid, label="police officer")
                if created:
                    Personnel.objects.filter(pk=officer.pk).update(supervisor=boss)
        self.head_and_staff(station, STATION_DEPARTMENTS)
        facilities.ensure_jail_center(station)
        self.detainees_for(station, region_name, boss)
        self.ob_for(station, boss)
        self.flush_ob(station)

    # ----------------------------------------------------------------------------------------------- detainees
    def detainees_for(self, station, region_name, boss):
        if DetentionRecord.objects.filter(org_unit=station, created_by_username="sample").exists():
            return
        rng = random.Random(f"{station.code}-detainees")
        for i in range(1, self.detainees + 1):
            booked = timezone.now() - timedelta(hours=rng.randint(3, 24 * 9))
            female = rng.random() < 0.15
            name = f"{rng.choice(FEMALE if female else MALE)} {rng.choice(FAMILY)} {rng.choice(FAMILY)}"
            counter, _ = DetentionCounter.objects.select_for_update().get_or_create(name="detention")
            counter.last += 1
            counter.save(update_fields=["last"])
            released = i == self.detainees and self.detainees > 1  # the last one of each station has already left
            rec = DetentionRecord.objects.create(
                facility=CustodyFacility.objects.filter(org_unit=station, kind="jail_center").first(), register_no=f"DET-{counter.last:06d}", org_unit=station, detainee_name=name, sex="female" if female else "male",
                age_years=rng.randint(17, 58), id_ref=f"SAMPLE-ID-{counter.last:06d}", address=f"{region_name} (sample address)",
                booked_at=booked, arrest_place=rng.choice(PLACES), arresting_officer=boss, arresting_officer_name=boss.full_name,
                reason=rng.choice(OFFENCES), authority_ref=f"SAMPLE-WARRANT-{counter.last:04d}",
                cell=CELLS[3] if female else rng.choice(CELLS[:3]), property_held="Phone, wallet (sample)",
                health_note="No health concerns noted (sample)", created_by_username="sample")
            DetentionEvent.objects.create(record=rec, kind="booked", occurred_at=booked, text=f"Booked in: {rec.reason}", by_username="sample")
            DetentionEvent.objects.create(record=rec, kind="welfare", occurred_at=booked + timedelta(hours=2), text="Welfare check: well, fed (sample)", by_username="sample")
            if released:
                end = min(timezone.now(), booked + timedelta(hours=rng.randint(4, 30)))
                DetentionRecord.objects.filter(pk=rec.pk).update(status="released", ended_at=end, outcome="bail", ended_by_username="sample",
                                                                 outcome_note="Released on guarantee (sample)", version=2)
                self._ob(station, "custody", end, f"Released on guarantee: {name}, held under {rec.register_no} (sample)", rec)
                DetentionEvent.objects.create(record=rec, kind="released", occurred_at=end, text="Released on bail / guarantee (sample)", by_username="sample")
            self._ob(station, "arrest", booked, f"Arrest: {name}, held under {rec.register_no} (sample)", rec, details=f"Ground: {rec.reason}.")
            self.stats["detainees"] += 1

    # ------------------------------------------------------------------------------------------ occurrence book
    def _ob(self, station, category, when, summary, det=None, details=""):
        self.pending.append((when, category, summary, det, details))  # written in time order by flush_ob, so OB numbers follow the clock

    def flush_ob(self, station):
        for when, category, summary, det, details in sorted(self.pending, key=lambda x: x[0]):
            year = timezone.localtime(when).year
            seq, number = next_number(station, year)
            OccurrenceEntry.objects.create(org_unit=station, ob_year=year, ob_seq=seq, ob_number=number, category=category, occurred_at=when,
                                           summary=summary[:300], details=details, detention_record=det, recorded_by_username="sample")
            self.stats["ob_entries"] += 1
        self.pending = []

    def ob_for(self, station, boss):
        """A few ordinary day-to-day entries (arrests and releases are entered with the detainees). Only once per station."""
        if OccurrenceEntry.objects.filter(org_unit=station, recorded_by_username="sample", category__in=[c for c, _ in OB_ENTRIES]).exists():
            return
        rng = random.Random(f"{station.code}-ob")
        for category, summary in OB_ENTRIES:
            self._ob(station, category, timezone.now() - timedelta(hours=rng.randint(1, 24 * 9)), summary, details=f"Recorded by {boss.full_name} (sample).")


class Command(BaseCommand):
    help = ("Add synthetic officers, staff, department heads and detainees to every regional command and to its two generic stations "
            "(Jeelka kowaad / Jeelka labaad). Sample deployments only. Safe to run again.")

    def add_arguments(self, parser):
        parser.add_argument("--officers", type=int, default=3, help="police officers in each Koox (default 3)")
        parser.add_argument("--detainees", type=int, default=4, help="detainees booked at each station (default 4)")

    def handle(self, *args, **opts):
        if not _sample_mode_allowed():
            raise CommandError("Sample data is disabled. Set ARMYHQ_SAMPLE_MODE=1 only for a synthetic sample deployment.")
        if not 1 <= opts["officers"] <= 20 or not 0 <= opts["detainees"] <= 30:
            raise CommandError("--officers must be 1-20 and --detainees 0-30.")
        if not OU.objects.filter(code="BARI-POL-S1").exists():
            # the stations come with the structure; build it first so this command works on a fresh database too
            from django.core.management import call_command
            call_command("apply_police_structure", "--apply", stdout=self.stdout)
        with transaction.atomic():
            facilities.ensure_defaults()
            seeder = Seeder(opts["officers"], opts["detainees"], self.stdout)
            for code, name in ps.REGIONS:
                self.stdout.write(f"{name}:")
                seeder.region(code, name)
        s = seeder.stats
        self.stdout.write(self.style.SUCCESS(
            f"Police sample data ready: {s['people']} people, {s['appointments']} appointments, {s['departments']} station departments, "
            f"{s['detainees']} detainees and {s['ob_entries']} Occurrence Book entries added (a second run adds nothing)."))
