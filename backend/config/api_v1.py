from django.conf import settings
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.accounts import views as acc
from apps.core.views import LiveView, ReadyView, ProfileView, SystemStatusView, HealthCheckView, TestEmailView, BackupHeartbeatView
from apps.audit.views import AuditEventViewSet
from apps.dashboard.views import DashboardActivityView, DashboardView, DueSoonView
from apps.personnel.combined import CombinedReportViewSet
from apps.personnel.views import PersonnelViewSet
from apps.personnel.task_views import UnitTaskViewSet
from apps.logistics.food_views import FoodAllocationViewSet, FoodOptionsViewSet, FoodReceiptViewSet, FoodWarningsViewSet, SupplierViewSet
from apps.logistics.views import (AmmunitionViewSet, AssetViewSet, CategoryViewSet, LogisticsSummaryViewSet, ReconciliationViewSet,
                                  StockViewSet)
from apps.attendance.views import AttendanceViewSet
from apps.leave.views import LeaveViewSet, RosterViewSet
from apps.medical.views import FitnessViewSet
from apps.promotion.views import PromotionViewSet
from apps.weapons.control_views import AmmoControlViewSet
from apps.weapons.views import WeaponViewSet
from apps.ppe.views import PpeViewSet
from apps.vehicles.views import VehicleViewSet
from apps.vehicles.logbook import VehicleLogViewSet
from apps.vehicles.maptiles import MapConfigView, MapTilesView
from apps.vehicles.tracking import TrackerFeedView, VehicleTrackingViewSet
from apps.personnel.report import PersonnelReportViewSet
from apps.equipment.views import EquipmentViewSet
from apps.payroll.views import PayrollRunViewSet, SalaryProfileViewSet, SurvivorCaseViewSet
from apps.payroll.views_ext import ArrearsViewSet, PayrollPersonnelViewSet, PaymentViewSet, PolicyViewSet
from apps.training.views import CourseViewSet, TrainingPeopleViewSet, TrainingRecordViewSet, TrainingSummaryViewSet
from apps.workflows.views import NotificationViewSet, ReportTypeViewSet, SubmissionViewSet, SummaryViewSet
from apps.organization.views import (ChangeRequestViewSet, DepartmentViewSet, DesignationViewSet, FormationRoleViewSet, OrgAnalyticsViewSet,
                                     RuleViewSet, ServiceBranchViewSet, StructureChangeViewSet, StructureViewSet, UnitDepartmentViewSet,
                                     UnitTypeViewSet, UnitViewSet)
from apps.ranks.views import RankViewSet
from apps.analytics.views import AnalyticsViewSet
from apps.inventories.views import InventoryViewSet
from apps.issuance.views import IssuedDocumentViewSet, VerifyView
from apps.schedules.views import AlertPreferenceView, ReportScheduleViewSet, RunDueView, UnitReportView
from apps.integrations.views import ExtAnalyticsView, ExtMeView, IntegrationClientViewSet

router = DefaultRouter()
router.include_root_view = False
router.register("users", acc.UserViewSet, basename="user")
router.register("roles", acc.RoleViewSet, basename="role")
router.register("organization/units", UnitViewSet, basename="unit")
router.register("organization/unit-types", UnitTypeViewSet, basename="unit-type")
router.register("organization/departments", DepartmentViewSet, basename="department")
router.register("organization/unit-departments", UnitDepartmentViewSet, basename="unit-department")
router.register("organization/formation-roles", FormationRoleViewSet, basename="formation-role")
router.register("organization/analytics", OrgAnalyticsViewSet, basename="org-analytics")
router.register("organization/designations", DesignationViewSet, basename="designation")
router.register("organization/designation-rules", RuleViewSet, basename="designation-rule")
router.register("organization/structure", StructureViewSet, basename="structure")
router.register("organization/structure-changes", StructureChangeViewSet, basename="structure-change")
router.register("organization/branches", ServiceBranchViewSet, basename="branch")
router.register("ranks", RankViewSet, basename="rank")
router.register("credentials", IssuedDocumentViewSet, basename="credential")
router.register("schedules", ReportScheduleViewSet, basename="report-schedule")
router.register("personnel", PersonnelViewSet, basename="personnel")
router.register("reports/types", ReportTypeViewSet, basename="report-type")
router.register("reports/submissions", SubmissionViewSet, basename="submission")
router.register("reports/summary", SummaryViewSet, basename="report-summary")
router.register("reports/combined", CombinedReportViewSet, basename="report-combined")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("logistics/categories", CategoryViewSet, basename="inv-category")
router.register("logistics/stock", StockViewSet, basename="stock")
router.register("logistics/assets", AssetViewSet, basename="asset")
router.register("logistics/ammunition", AmmunitionViewSet, basename="ammunition")
router.register("logistics/reconciliations", ReconciliationViewSet, basename="reconciliation")
router.register("logistics/summary", LogisticsSummaryViewSet, basename="logistics-summary")
router.register("organization/change-requests", ChangeRequestViewSet, basename="change-request")
router.register("operations/tasks", UnitTaskViewSet, basename="unit-task")
router.register("logistics/suppliers", SupplierViewSet, basename="food-supplier")
router.register("logistics/food/receipts", FoodReceiptViewSet, basename="food-receipt")
router.register("logistics/food/allocations", FoodAllocationViewSet, basename="food-allocation")
router.register("logistics/food/warnings", FoodWarningsViewSet, basename="food-warning")
router.register("logistics/food/options", FoodOptionsViewSet, basename="food-options")
router.register("attendance", AttendanceViewSet, basename="attendance")
router.register("leave", LeaveViewSet, basename="leave")
router.register("roster", RosterViewSet, basename="roster")
router.register("promotion", PromotionViewSet, basename="promotion")
router.register("fitness", FitnessViewSet, basename="fitness")
router.register("weapons", WeaponViewSet, basename="weapons")
router.register("ammo-control", AmmoControlViewSet, basename="ammo-control")
router.register("ppe", PpeViewSet, basename="ppe")
router.register("vehicle-log", VehicleLogViewSet, basename="vehicle-log")
router.register("vehicle-tracking", VehicleTrackingViewSet, basename="vehicle-tracking")
router.register("personnel-report", PersonnelReportViewSet, basename="personnel-report")

router.register("vehicles", VehicleViewSet, basename="vehicle")
router.register("equipment", EquipmentViewSet, basename="equipment")
router.register("payroll/profiles", SalaryProfileViewSet, basename="payroll-profile")
router.register("payroll/runs", PayrollRunViewSet, basename="payroll-run")
router.register("survivor-cases", SurvivorCaseViewSet, basename="survivor-case")
router.register("payroll/payments", PaymentViewSet, basename="payroll-payment")
router.register("payroll/arrears", ArrearsViewSet, basename="payroll-arrears")
router.register("payroll/personnel", PayrollPersonnelViewSet, basename="payroll-personnel")
router.register("payroll/policy", PolicyViewSet, basename="payroll-policy")
router.register("training/courses", CourseViewSet, basename="course")
router.register("training/records", TrainingRecordViewSet, basename="training-record")
router.register("training/people", TrainingPeopleViewSet, basename="training-person")
router.register("training/summary", TrainingSummaryViewSet, basename="training-summary")
router.register("audit-events", AuditEventViewSet, basename="audit-event")
router.register("analytics", AnalyticsViewSet, basename="analytics")
router.register("integrations/clients", IntegrationClientViewSet, basename="integration-client")
router.register("inventories", InventoryViewSet, basename="inventory")

urlpatterns = [
    path("auth/csrf/", acc.CsrfView.as_view()),
    path("auth/login/", acc.LoginView.as_view()),
    path("auth/logout/", acc.LogoutView.as_view()),
    path("auth/me/", acc.MeView.as_view()),
    path("auth/me/photo/", acc.MyPhotoView.as_view()),
    path("auth/password/change/", acc.PasswordChangeView.as_view()),
    path("auth/password/reset/", acc.PasswordResetView.as_view()),
    path("auth/password/forgot/", acc.PasswordForgotView.as_view()),
    path("auth/email/verify/request/", acc.EmailVerifyRequestView.as_view()),
    path("auth/email/verify/confirm/", acc.EmailVerifyConfirmView.as_view()),
    path("auth/options/", acc.AuthOptionsView.as_view()),
    path("auth/mfa/recover/request/", acc.MfaRecoveryRequestView.as_view()),
    path("auth/mfa/recover/redeem/", acc.MfaRecoveryRedeemView.as_view()),
    path("auth/mfa/setup/", acc.MfaSetupView.as_view()),
    path("auth/mfa/confirm/", acc.MfaConfirmView.as_view()),
    path("auth/step-up/", acc.StepUpView.as_view()),
    path("auth/step-up/passkey/", acc.PasskeyStepUpOptionsView.as_view()),
    path("auth/mfa/backup-codes/", acc.BackupCodesView.as_view()),
    path("auth/sessions/", acc.MySessionsView.as_view()),
    path("auth/sessions/<str:sid>/", acc.MySessionDetailView.as_view()),
    path("auth/passkeys/", acc.PasskeyListView.as_view()),
    path("auth/passkeys/register/options/", acc.PasskeyRegisterOptionsView.as_view()),
    path("auth/passkeys/register/verify/", acc.PasskeyRegisterVerifyView.as_view()),
    path("auth/passkeys/<uuid:pk>/", acc.PasskeyDetailView.as_view()),
    path("map/config/", MapConfigView.as_view()),
    path("map/puntland.pmtiles", MapTilesView.as_view()),  # self-hosted map tiles (HTTP Range)
    path("tracker/feed/", TrackerFeedView.as_view()),  # GPS trackers (key-authenticated, add-position only)
    path("dashboard/", DashboardView.as_view()),
    path("dashboard/activity/", DashboardActivityView.as_view()),
    path("due-soon/", DueSoonView.as_view()),
    path("profile/", ProfileView.as_view()),
    path("system/status/", SystemStatusView.as_view()),
    path("system/health-check/", HealthCheckView.as_view()),
    path("system/health-check/test-email/", TestEmailView.as_view()),
    path("system/heartbeat/backup/", BackupHeartbeatView.as_view()),
    path("verify/<str:code>/", VerifyView.as_view()),  # public: QR check of an ID card or letter
    path("alerts/preferences/", AlertPreferenceView.as_view()),  # which event emails a person receives
    path("unit-report/", UnitReportView.as_view()),  # PDF: strength, leave, weapons, vehicles and fuel for one unit
    path("schedules/run-due/", RunDueView.as_view()),  # token-protected trigger for an outside scheduler
    path("health/live/", LiveView.as_view()),
    path("health/ready/", ReadyView.as_view()),
    # External (machine-client) API, 2.0: bearer-key auth, read-only, aggregate analytics only.
    path("ext/me/", ExtMeView.as_view()),
    path("ext/analytics/<str:section>/", ExtAnalyticsView.as_view()),
] + router.urls

if settings.ENABLE_API_DOCS:
    urlpatterns += [
        path("schema/", SpectacularAPIView.as_view(), name="schema"),
        path("docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    ]
