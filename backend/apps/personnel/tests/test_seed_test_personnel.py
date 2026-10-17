from django.core.management import call_command

from apps.core.testing import BaseApiTest
from apps.personnel.models import Personnel, PersonnelHistory


class SeedTestPersonnelTests(BaseApiTest):
    def test_adds_150_unique_people_with_varied_ranks_and_removes_them_all(self):
        real = None
        from apps.organization.models import OrganizationalUnit as OU
        from apps.personnel import services as svc
        from apps.ranks.models import Rank
        unit = OU.objects.create(code="BARI-ARMY-REAL", name_en="Real", level="unit", parent=OU.objects.get(code="BARI-ARMY"))
        real = svc.create_personnel(None, full_name="Real Person", phone="", service_number="REAL-1", org_unit=unit,
                                    rank=Rank.objects.filter(branch__code="ARMY", approval_status="approved").first(),
                                    status="active", effective_date=None)

        call_command("seed_test_personnel", count=150, verbosity=0)
        tst = Personnel.objects.filter(service_number__startswith="TST-")
        self.assertEqual(tst.count(), 150)
        self.assertEqual(len({p.name_key for p in tst}), 150)          # no duplicate names
        self.assertGreater(len({p.rank_id for p in tst}), 10)           # many different ranks
        self.assertGreater(len({p.org_unit_id for p in tst}), 3)        # spread over the regions

        from apps.personnel import profile as profile_svc
        from apps.personnel.models import PersonnelProfile
        for p in tst[:5]:                                              # identity profile is pre-filled
            prof = profile_svc.read(p)
            self.assertTrue(prof["blood_type"] and prof["gender"] and prof["home_district"] and prof["has_photo"])
            self.assertTrue(prof["date_of_birth"] and prof["enlistment_date"] and prof["emergency_contact_phone"])
        self.assertEqual(PersonnelProfile.objects.filter(personnel__in=tst).count(), 150)
        weapons = list(PersonnelProfile.objects.filter(personnel__in=tst).exclude(weapon_key=None).values_list("weapon_key", flat=True))
        self.assertEqual(len(weapons), len(set(weapons)))              # weapon IDs are unique

        call_command("seed_test_personnel", count=150, verbosity=0)     # idempotent
        self.assertEqual(Personnel.objects.filter(service_number__startswith="TST-").count(), 150)

        call_command("seed_test_personnel", delete=True, verbosity=0)
        self.assertFalse(Personnel.objects.filter(service_number__startswith="TST-").exists())
        self.assertFalse(PersonnelHistory.objects.filter(personnel__service_number__startswith="TST-").exists())
        self.assertFalse(PersonnelProfile.objects.filter(personnel__service_number__startswith="TST-").exists())
        self.assertTrue(Personnel.objects.filter(pk=real.pk).exists())   # real records untouched

    def test_from_env_zero_deletes_and_never_raises(self):
        import os
        call_command("seed_test_personnel", count=5, verbosity=0)
        os.environ["ARMYHQ_TEST_PERSONNEL"] = "0"
        try:
            call_command("seed_test_personnel", from_env=True, verbosity=0)
        finally:
            os.environ.pop("ARMYHQ_TEST_PERSONNEL", None)
        self.assertFalse(Personnel.objects.filter(service_number__startswith="TST-").exists())
