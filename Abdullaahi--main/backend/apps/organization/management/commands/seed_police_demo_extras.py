"""Synthetic demo records for the parts of the Police system that `seed_police_sample` does not fill.

  python manage.py seed_police_demo_extras

Runs `seed_police_sample` first (people, appointments, departments, detainees, Occurrence Book; safe to repeat), then adds, for the
first station of every regional command:

  * vehicles (state plates GD-9xx) with a driver, a condition, and a completed and an open maintenance record;
  * civilian vehicles and road-tax receipts for the tax module (receipt numbers SMP-R-...);
  * training records for sample officers on the seeded courses (enrolled, in progress, completed);
  * today's attendance for the station's sample officers (present, one absent with a reason);
  * one open and one completed administrative task per regional command;
  * a general-supplies stock line per station.

Not covered here (they need approval chains with several different users, so a demo is better done by hand on screen): payroll runs,
survivor benefits, weapons, ammunition, arrears, reports and approvals.

Every record carries "SMP", "SAMPLE" or created_by "sample" so it can be recognised. Idempotent: a second run adds nothing.
Each section is separate: if one fails it is reported and the others still run. NEVER use with real data.
Allowed only on a sample deployment (DEBUG, or POLICEHQ_SAMPLE_MODE=1).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core import env as hqenv
from apps.organization import police_structure as ps
from apps.organization.models import OrganizationalUnit as OU
from apps.personnel.models import Personnel

TAG = "sample"


def _sample_mode_allowed():
    raw = hqenv.get("SAMPLE_MODE", "0", legacy=("DEMO_MODE",))
    return settings.DEBUG or raw.strip().lower() in ("1", "true", "yes", "on")


def _key(plate):
    return "".join(ch for ch in (plate or "").upper() if ch.isalnum())


class Command(BaseCommand):
    help = "Add synthetic demo vehicles, tax receipts, training, attendance, tasks and stock (sample deployments only)."

    def handle(self, *args, **opts):
        if not _sample_mode_allowed():
            raise CommandError("Sample data is disabled. Set POLICEHQ_SAMPLE_MODE=1 only for a synthetic sample deployment.")
        call_command("seed_police_sample", stdout=self.stdout)
        self.today = date.today()
        self.stations = []
        for code, name in ps.REGIONS:
            unit = OU.objects.filter(code=f"{code}-POL-S1").first()
            if unit:
                self.stations.append((code, name, unit))
        if not self.stations:
            raise CommandError("No stations found. Run `manage.py apply_police_structure --apply` first.")
        for label, fn in (("vehicles", self.vehicles), ("tax", self.tax), ("training", self.training),
                          ("attendance", self.attendance), ("tasks", self.tasks), ("stock", self.stock)):
            try:
                with transaction.atomic():
                    added = fn()
                self.stdout.write(self.style.SUCCESS(f"{label}: {added} added"))
            except Exception as exc:  # one failing section must not stop the others
                self.stdout.write(self.style.WARNING(f"{label}: skipped ({type(exc).__name__}: {exc})"))

    def people(self, station):
        """Active sample people in the station or in any unit below it (its Kooxo)."""
        return list(Personnel.objects.filter(service_number__startswith="SMP-", org_unit__path__startswith=station.path,
                                             status="active").order_by("service_number"))

    # ---- vehicles -------------------------------------------------------------------------------------------------
    def vehicles(self):
        from apps.vehicles.models import MaintenanceRecord, Vehicle as V, VehicleCategory, VehicleCounter, VehicleEvent
        cats = {c.code: c for c in VehicleCategory.objects.filter(code__in=["police_pickup", "police_transport", "police_motorcycle"])}
        if not cats:
            raise RuntimeError("Police vehicle categories are missing (run apply_police_fleet --apply)")
        plan = [("police_pickup", "Toyota", "Hilux", 2021), ("police_transport", "Isuzu", "NPR", 2019)]
        made, n = 0, 0
        for ri, (_, _, station) in enumerate(self.stations):
            crew = self.people(station)
            used = set(V.objects.exclude(driver=None).values_list("driver_id", flat=True))
            for vi, (cat_code, make, model, year) in enumerate(plan):
                n += 1
                plate = f"GD-9{ri}{vi}"
                if V.objects.filter(plate_key=_key(plate)).exists() or cat_code not in cats:
                    continue
                driver = next((p for p in crew if p.pk not in used), None)
                if driver:
                    used.add(driver.pk)
                counter, _ = VehicleCounter.objects.select_for_update().get_or_create(name="vehicle")
                counter.last += 1
                counter.save(update_fields=["last"])
                v = V.objects.create(
                    vehicle_id=f"VEH-{counter.last:06d}", plate=plate, plate_key=_key(plate), plate_status=V.PlateStatus.REGISTERED,
                    ownership=V.Ownership.STATE, category=cats[cat_code], make=make, model=model, year=year, org_unit=station,
                    driver=driver, custodian=crew[0] if crew else None, location="Station yard (sample)", status=V.Status.OPERATIONAL,
                    condition=V.Condition.GOOD if vi == 0 else V.Condition.FAIR, acquired_on=self.today - timedelta(days=400 + vi * 90),
                    acquisition_ref="Sample order 2/2026", notes="Synthetic sample vehicle", created_by_username=TAG)
                VehicleEvent.objects.create(vehicle=v, kind=VehicleEvent.Kind.REGISTERED, after={"plate": plate, "sample": True},
                                            actor_username=TAG, authority_ref="Sample order 2/2026")
                MaintenanceRecord.objects.create(
                    vehicle=v, kind=MaintenanceRecord.Kind.SERVICE, state=MaintenanceRecord.State.COMPLETED,
                    performed_on=self.today - timedelta(days=60), work_performed="Oil and filter change (sample)", workshop="Sample workshop",
                    next_due_date=self.today + timedelta(days=120), reference=f"SMP-SVC-{counter.last}", created_by_username=TAG)
                if vi == 1:
                    MaintenanceRecord.objects.create(
                        vehicle=v, kind=MaintenanceRecord.Kind.REPAIR, state=MaintenanceRecord.State.OPEN,
                        performed_on=self.today - timedelta(days=3), reported_issue="Brake noise reported by driver (sample)",
                        workshop="Sample workshop", next_due_date=self.today + timedelta(days=10), created_by_username=TAG)
                made += 1
        return made

    # ---- tax --------------------------------------------------------------------------------------------------------
    def tax(self):
        from apps.tax.models import TaxPayment, TaxType, TaxVehicle
        road = TaxType.objects.filter(code__in=["road_tax", "road-tax"]).first() or TaxType.objects.filter(kind="road_tax").first()
        fine = TaxType.objects.filter(kind="fine").first()
        if not road:
            raise RuntimeError("Tax types are missing (run seed_reference_data)")
        made = 0
        owners = ["Sample Owner A", "Sample Owner B", "Sample Owner C"]
        kinds = [("car", "Toyota Corolla"), ("truck", "Isuzu FVR"), ("motorbike", "Honda CG125")]
        for ri, (_, _, station) in enumerate(self.stations):
            for k in range(3):
                plate = f"PL-8{ri}{k}"
                tv = TaxVehicle.objects.filter(plate_key=_key(plate)).first()
                if not tv:
                    tv = TaxVehicle.objects.create(
                        plate=plate, plate_key=_key(plate), owner_name=owners[k], owner_phone=f"+2529100{ri}{k}00", id_ref=f"SAMPLE-ID-V{ri}{k}",
                        vehicle_kind=kinds[k][0], make_model=kinds[k][1], org_unit=station, notes="Synthetic sample vehicle",
                        created_by_username=TAG)
                    made += 1
                receipt = f"SMP-R-{ri}{k}1"
                if TaxPayment.objects.filter(org_unit=station, receipt_no=receipt).exists():
                    continue
                # vehicles 0 and 1 are paid up; vehicle 2 has an expired period so the Overdue flag shows
                start = self.today - timedelta(days=60 if k < 2 else 500)
                TaxPayment.objects.create(
                    receipt_no=receipt, org_unit=station, vehicle=tv, tax_type=road, amount=Decimal("25.00"), currency=road.currency,
                    paid_on=start, period_from=start, period_to=start + timedelta(days=365), collected_by_username=TAG)
                made += 1
            if fine:
                tv = TaxVehicle.objects.filter(plate_key=_key(f"PL-8{ri}0")).first()
                receipt = f"SMP-F-{ri}01"
                if tv and not TaxPayment.objects.filter(org_unit=station, receipt_no=receipt).exists():
                    TaxPayment.objects.create(
                        receipt_no=receipt, org_unit=station, vehicle=tv, tax_type=fine, amount=Decimal("10.00"), currency=fine.currency,
                        paid_on=self.today - timedelta(days=5), reference="SAMPLE-TICKET-001", collected_by_username=TAG)
                    made += 1
        return made

    # ---- training ---------------------------------------------------------------------------------------------------
    def training(self):
        from apps.training.models import Course, TrainingRecord as T
        courses = list(Course.objects.filter(active=True).order_by("code")[:3])
        if not courses:
            raise RuntimeError("No courses found (run seed_reference_data)")
        made = 0
        for _, _, station in self.stations:
            for i, person in enumerate(self.people(station)[:3]):
                course = courses[i % len(courses)]
                if T.objects.filter(personnel=person, course=course).exists():
                    continue
                if i == 0:
                    kw = dict(status=T.Status.COMPLETED, start_date=self.today - timedelta(days=90),
                              end_date=self.today - timedelta(days=80), completed_on=self.today - timedelta(days=80))
                elif i == 1:
                    kw = dict(status=T.Status.IN_PROGRESS, start_date=self.today - timedelta(days=7))
                else:
                    kw = dict(status=T.Status.ENROLLED, start_date=self.today + timedelta(days=14))
                T.objects.create(personnel=person, course=course, notes="Synthetic sample record", created_by_username=TAG, **kw)
                made += 1
        return made

    # ---- attendance -------------------------------------------------------------------------------------------------
    def attendance(self):
        from apps.attendance.models import AbsenceReason, AttendanceRecord as A
        reason = AbsenceReason.objects.filter(active=True, requires_document=False).order_by("code").first()
        made = 0
        for _, _, station in self.stations:
            for i, person in enumerate(self.people(station)[:6]):
                if A.objects.filter(personnel=person, report_date=self.today).exists():
                    continue
                absent = i == 3 and reason is not None
                A.objects.create(
                    personnel=person, org_unit=person.org_unit, report_date=self.today,
                    status=A.Status.ABSENT if absent else A.Status.PRESENT, reason=reason if absent else None,
                    note="Synthetic sample entry", reported_by_username=TAG)
                made += 1
        return made

    # ---- tasks ------------------------------------------------------------------------------------------------------
    def tasks(self):
        from apps.personnel.models import UnitTask
        made = 0
        for code, name in ps.REGIONS:
            unit = OU.objects.filter(code=f"{code}-POL").first() or OU.objects.filter(code=f"{code}-POLICE").first()
            if not unit:
                unit = next((s for c, _, s in self.stations if c == code), None)
            if not unit:
                continue
            boss = next(iter(self.people(unit)), None)
            for title, status in ((f"Quarterly station inspection, {name} (sample)", UnitTask.Status.OPEN),
                                  (f"Update duty roster, {name} (sample)", UnitTask.Status.COMPLETED)):
                if UnitTask.objects.filter(org_unit=unit, title=title).exists():
                    continue
                done = status == UnitTask.Status.COMPLETED
                UnitTask.objects.create(
                    org_unit=unit, title=title, description="Synthetic sample task", authority_ref="Sample order 3/2026",
                    assigned_on=self.today - timedelta(days=20), due_on=self.today + (timedelta(days=-5) if done else timedelta(days=15)),
                    status=status, responsible=boss, completion_report="Completed as instructed (sample)." if done else "",
                    document_ref="SAMPLE-DOC-3" if done else "", completed_at=None, created_by_username=TAG)
                made += 1
        return made

    # ---- stock ------------------------------------------------------------------------------------------------------
    def stock(self):
        from apps.logistics.models import InventoryCategory, StockLine, StockTransaction
        cat = InventoryCategory.objects.filter(code="general_supplies").first()
        if not cat:
            raise RuntimeError("general_supplies category is missing (run seed_reference_data)")
        InventoryCategory.objects.filter(pk=cat.pk).update(approval_status="approved")  # a harmless sample category, as seed_sample_data does
        made = 0
        for _, _, station in self.stations:
            if StockLine.objects.filter(category=cat, org_unit=station).exists():
                continue
            line = StockLine.objects.create(category=cat, org_unit=station, quantity=40, reorder_level=50 if made % 2 == 0 else 10, uom="boxes")
            StockTransaction.objects.create(stock_line=line, kind="opening", delta=40, balance_after=40, reason="Synthetic sample opening balance",
                                            actor_username=TAG)
            made += 1
        return made
