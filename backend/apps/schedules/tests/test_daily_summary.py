"""The daily station summary: today's attendance and due-soon counts, only where everyone receiving it may see them."""
from apps.core.testing import BaseApiTest
from apps.schedules import services
from apps.schedules.models import ReportSchedule


class DailySummaryTests(BaseApiTest):
    def schedule(self, creator):
        return ReportSchedule.objects.create(name="Daily", org_unit=self.unit("HQ"), frequency="daily", created_by=creator)

    def test_attendance_lines_appear_when_creator_and_recipients_may_see_them(self):
        adm = self.make_user("adm", "hq_admin")
        s = self.schedule(adm)
        text = "\n".join(services.today_section(s, adm, [adm]))
        self.assertIn("TODAY'S ATTENDANCE", text)
        self.assertIn("Present", text)

    def test_nothing_is_shown_that_a_recipient_may_not_see(self):
        adm = self.make_user("adm", "hq_admin")
        reader = self.make_user("walker", "member", mfa=False)
        s = self.schedule(adm)
        self.assertEqual(services.today_section(s, adm, [reader]), [])
