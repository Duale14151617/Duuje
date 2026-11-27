"""Dashboard trend figures and the leave-approval block: scoped to what the caller may see. Synthetic data only."""
from datetime import timedelta

from django.utils import timezone

from apps.leave.models import LeaveRequest
from apps.leave.tests.test_leave import LeaveBase
from apps.personnel.models import Personnel

URL = "/api/v1/dashboard/"


class DashboardTrendTests(LeaveBase):
    def test_new_records_trend_counts_only_the_callers_scope(self):
        self.person("BARI-ARMY-B", "Elsewhere One")
        # age two of the unit-A people into the previous 30-day window and one beyond it
        old = timezone.now() - timedelta(days=40)
        Personnel.objects.filter(pk=self.p2.pk).update(created_at=old)
        mine = self.cmdr.get(URL).data["personnel"]
        everyone = self.client_for(self.make_user("sa.trend", "super_admin")).get(URL).data["personnel"]
        self.assertEqual((mine["new_30d"], mine["new_prev_30d"]), (1, 1))  # p1 new; p2 aged into the previous window; unit B not counted
        self.assertGreater(everyone["new_30d"], mine["new_30d"])
        very_old = timezone.now() - timedelta(days=100)
        Personnel.objects.filter(pk=self.p2.pk).update(created_at=very_old)
        self.assertEqual(self.cmdr.get(URL).data["personnel"]["new_prev_30d"], 0)

    def test_leave_block_only_for_approvers_and_counts_pending_in_scope(self):
        self.assertEqual(self.ask().status_code, 201)  # the member asks for leave
        data = self.cmdr.get(URL).data
        self.assertEqual(data["leave"]["pending_approval"], 1)
        self.assertEqual(data["leave"]["requests_7d"], 1)
        self.assertEqual(self.other_cmdr.get(URL).data["leave"]["pending_approval"], 0)  # another unit's approver never sees this request
        self.assertNotIn("leave", self.member.get(URL).data)  # an ordinary member holds no approval permission

    def test_a_request_the_approver_made_for_themselves_is_not_theirs_to_decide(self):
        LeaveRequest.objects.update(status="cancelled")
        self.ask()
        LeaveRequest.objects.update(requested_by_id=self.cmdr_user.pk)
        self.assertEqual(self.cmdr.get(URL).data["leave"]["pending_approval"], 0)

    def test_requests_trend_compares_this_week_with_the_week_before(self):
        self.ask()
        LeaveRequest.objects.update(created_at=timezone.now() - timedelta(days=10))
        leave = self.cmdr.get(URL).data["leave"]
        self.assertEqual((leave["requests_7d"], leave["requests_prev_7d"]), (0, 1))
