"""Police Fleet Management: the Police vehicle types under the main category Police Vehicles. Synthetic data only."""
from django.core.management import call_command

from apps.audit.models import AuditEvent
from apps.vehicles import police_fleet
from apps.vehicles.models import Vehicle, VehicleCategory
from apps.vehicles.tests.test_vehicles import URL, VehicleBase


class PoliceFleetTests(VehicleBase):
    def test_six_police_types_created_under_main_category(self):
        call_command("apply_police_fleet", "--apply")
        cats = {c.code: c for c in VehicleCategory.objects.filter(group=police_fleet.MAIN_CATEGORY)}
        self.assertEqual(set(cats), {c[0] for c in police_fleet.POLICE_VEHICLE_CATEGORIES})
        self.assertEqual(len(cats), 6)
        self.assertTrue(all(c.active for c in cats.values()))
        self.assertTrue(AuditEvent.objects.filter(action="vehicle.police_fleet_applied").exists())

    def test_dry_run_writes_nothing_and_rerun_is_idempotent(self):
        call_command("apply_police_fleet")
        self.assertFalse(VehicleCategory.objects.filter(code="police_pickup").exists())
        call_command("apply_police_fleet", "--apply")
        n = VehicleCategory.objects.count()
        call_command("apply_police_fleet", "--apply")
        self.assertEqual(VehicleCategory.objects.count(), n)

    def test_register_assign_and_filter_a_police_vehicle(self):
        call_command("apply_police_fleet", "--apply")
        v = self.veh(category="police_prisoner_transport", plate="GD-P01", custodian=str(self.d1.pk))
        self.assertEqual(v.category.group, "police_vehicles")
        self.assertTrue(v.vehicle_id)
        self.assertEqual(v.custodian_id, self.d1.pk)  # the responsible officer
        r = self.officer.get(URL, {"group": "police_vehicles"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(str(v.pk), {row["id"] for row in r.data["results"]})

    def test_unused_military_categories_retired_but_used_ones_kept(self):
        self.veh(category="armored_truck", plate="GD-P02")
        call_command("apply_police_fleet", "--apply")
        self.assertTrue(VehicleCategory.objects.get(code="armored_truck").active)  # a vehicle still uses it
        self.assertFalse(VehicleCategory.objects.get(code="main_battle_tank").active)
        self.assertEqual(Vehicle.objects.count(), 1)
