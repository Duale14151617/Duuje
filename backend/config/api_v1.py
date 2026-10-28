from django.conf import settings
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.accounts import views as acc
from apps.core.views import LiveView, ReadyView
from apps.audit.views import AuditEventViewSet
from apps.dashboard.views import DashboardView
from apps.personnel.combined import CombinedReportViewSet
from apps.personnel.views import PersonnelViewSet
from apps.logistics.food_views import FoodAllocationViewSet, FoodOptionsViewSet, FoodReceiptViewSet, FoodWarningsViewSet, SupplierViewSet
from apps.logistics.views import (AmmunitionViewSet, AssetViewSet, CategoryViewSet, LogisticsSummaryViewSet, ReconciliationViewSet,
                                  StockViewSet)
from apps.attendance.views import AttendanceViewSet
from apps.weapons.views import WeaponViewSet
from apps.vehicles.views import VehicleViewSet
from apps.payroll.views import PayrollRunViewSet, SalaryProfileViewSet, SurvivorCaseViewSet
from apps.payroll.views_ext import ArrearsViewSet, PayrollPersonnelViewSet, PaymentViewSet, PolicyViewSet
from apps.training.views import CourseViewSet, TrainingPeopleViewSet, TrainingRecordViewSet, TrainingSummaryViewSet
from apps.workflows.views import NotificationViewSet, ReportTypeViewSet, SubmissionViewSet, SummaryViewSet
from apps.organization.views import (DesignationViewSet, RuleViewSet, ServiceBranchViewSet, StructureChangeViewSet,
                                     StructureViewSet, UnitTypeViewSet, UnitViewSet)
from apps.ranks.views import RankViewSet
from apps.analytics.views import AnalyticsViewSet
from apps.integrations.views import ExtAnalyticsView, ExtMeView, IntegrationClientViewSet

router = DefaultRouter()
router.include_root_view = False
router.register("users", acc.UserViewSet, basename="user")
router.register("roles", acc.RoleViewSet, basename="role")
router.register("organization/units", UnitViewSet, basename="unit")
router.register("organization/unit-types", UnitTypeViewSet, basename="unit-type")
router.register("organization/designations", DesignationViewSet, basename="designation")
router.register("organization/designation-rules", RuleViewSet, basename="designation-rule")
router.register("organization/structure", StructureViewSet, basename="structure")
router.register("organization/structure-changes", StructureChangeViewSet, basename="structure-change")
router.register("organization/branches", ServiceBranchViewSet, basename="branch")
router.register("ranks", RankViewSet, basename="rank")
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
router.register("logistics/suppliers", SupplierViewSet, basename="food-supplier")
router.register("logistics/food/receipts", FoodReceiptViewSet, basename="food-receipt")
router.register("logistics/food/allocations", FoodAllocationViewSet, basename="food-allocation")
router.register("logistics/food/warnings", FoodWarningsViewSet, basename="food-warning")
router.register("logistics/food/options", FoodOptionsViewSet, basename="food-options")
router.register("attendance", AttendanceViewSet, basename="attendance")
router.register("weapons", WeaponViewSet, basename="weapons")
router.register("vehicles", VehicleViewSet, basename="vehicle")
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

urlpatterns = [
    path("auth/csrf/", acc.CsrfView.as_view()),
    path("auth/login/", acc.LoginView.as_view()),
    path("auth/logout/", acc.LogoutView.as_view()),
    path("auth/me/", acc.MeView.as_view()),
    path("auth/password/change/", acc.PasswordChangeView.as_view()),
    path("auth/password/reset/", acc.PasswordResetView.as_view()),
    path("auth/mfa/setup/", acc.MfaSetupView.as_view()),
    path("auth/mfa/confirm/", acc.MfaConfirmView.as_view()),
    path("dashboard/", DashboardView.as_view()),
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
