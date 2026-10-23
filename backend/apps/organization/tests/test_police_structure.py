"""Police structure as working units. Police only; Army and Navy are untouched. Synthetic data only."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.organization.models import OrganizationalUnit as OU

from .test_structure import TemplateBase

REGIONS = ("BARI", "KARKAAR", "NUGAAL", "MUDUG", "SANAAG")


@override_settings(POLICE_MODULE_ENABLED=True)
class PoliceStructureTests(TemplateBase):
    def run_cmd(self, apply=False, *extra):
        out = StringIO()
        call_command("apply_police_structure", *(["--apply"] if apply else []), *extra, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        before = OU.objects.count()
        self.assertIn("create_unit: SANAAG-POLICE", self.run_cmd())
        self.assertEqual(OU.objects.count(), before)

    def test_every_region_gets_command_departments_and_a_station(self):
        self.run_cmd(apply=True)
        for r in REGIONS:
            cmd = OU.objects.get(code=f"{r}-POLICE")
            self.assertEqual((cmd.level, cmd.branch.code), ("branch_command", "POLICE"))
            kids = {u.code: u for u in OU.objects.filter(parent=cmd)}
            for d in ("PERS", "OPS", "TRN", "FINLOG", "CID", "PR", "TRAFFIC"):
                self.assertEqual(kids[f"{r}-POLICE-{d}"].branch.code, "POLICE")
            self.assertTrue(kids[f"{r}-POLICE-CID"].restricted)
            self.assertFalse(kids[f"{r}-POLICE-OPS"].restricted)
            st = kids[f"{r}-POLICE-ST1"]
            self.assertEqual((st.level, st.branch.code), ("station", "POLICE"))

    def test_idempotent_and_raising_the_number_only_adds(self):
        self.run_cmd(apply=True)
        count = OU.objects.count()
        self.assertIn("already matches", self.run_cmd(apply=True))
        self.assertEqual(OU.objects.count(), count)
        self.run_cmd(True, "--stations-per-command", "3")
        self.assertEqual(OU.objects.count(), count + 2 * len(REGIONS))
        self.run_cmd(True)  # a smaller number later removes nothing
        self.assertEqual(OU.objects.count(), count + 2 * len(REGIONS))

    def test_army_and_navy_are_untouched(self):
        def snap():
            return list(OU.objects.filter(branch__code__in=["ARMY", "NAVY"]).order_by("code").values_list("code", "name_en", "version", "active"))
        before = snap()
        self.run_cmd(apply=True)
        self.assertEqual(snap(), before)

    def test_out_of_range_is_refused(self):
        for bad in ("0", "21"):
            with self.assertRaises(CommandError):
                self.run_cmd(True, "--stations-per-command", bad)

    @override_settings(POLICE_MODULE_ENABLED=False)
    def test_nothing_is_created_while_the_pilot_switch_is_off(self):
        before = OU.objects.count()
        self.assertIn("OFF", self.run_cmd(apply=True))
        self.assertEqual(OU.objects.count(), before)
