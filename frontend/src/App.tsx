import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { AuditLog } from "./pages/AuditLog";
import { Dashboard } from "./pages/Dashboard";
import { ForcedPassword, MfaEnrol } from "./pages/Enrol";
import { Login } from "./pages/Login";
import { ResetPassword } from "./pages/Reset";
import { ForgotPassword } from "./pages/ForgotPassword";
import { Account } from "./pages/Account";
import { RecoverMfa } from "./pages/RecoverMfa";
import { Attendance } from "./pages/Attendance";
import { Leave } from "./pages/Leave";
import { Promotion } from "./pages/Promotion";
import { Fitness } from "./pages/Fitness";
import { Ammunition } from "./pages/Ammunition";
import { Weapons } from "./pages/Weapons";
import { Inventories } from "./pages/Inventories";
import { Ppe } from "./pages/Ppe";
import { VehicleDetail, Vehicles } from "./pages/Vehicles";
import { VehicleLog } from "./pages/VehicleLog";
import { VehicleTracking } from "./pages/VehicleTracking";
import { CustodyFacilities } from "./pages/CustodyFacilities";
import { DetentionOversight } from "./pages/DetentionOversight";
import { CustodyIncidents } from "./pages/CustodyIncidents";
import { Detention } from "./pages/Detention";
import { OccurrenceBook } from "./pages/OccurrenceBook";
import { PersonnelReport } from "./pages/PersonnelReport";
import { ShiftHandover } from "./pages/ShiftHandover";
import { TaxOversight } from "./pages/TaxOversight";
import { OfflineDesk } from "./offline/OfflineDesk";
import { SHOW_OFFLINE_DESK } from "./offline/config";
import { Tax } from "./pages/Tax";
import { Equipment, EquipmentDetail } from "./pages/Equipment";
import { Holdings } from "./pages/Holdings";
import { AmmoAccountability } from "./pages/AmmoAccountability";
import { AmmoControl } from "./pages/AmmoControl";
import { Survivors } from "./pages/Survivors";
import { Payroll } from "./pages/Payroll";
import { ReportingLines } from "./pages/ReportingLines";
import { UsersBulk } from "./pages/UsersBulk";
import { AccessReview } from "./pages/AccessReview";
import { PersonnelDetail, PersonnelForm, PersonnelImport, PersonnelList } from "./pages/Personnel";
import { AssetDetail, LogisticsHome, ReconDetail, StockDetail } from "./pages/Logistics";
import { TrainingHome, TrainingRecordDetail } from "./pages/Training";
import { Notifications } from "./pages/Notifications";
import { CrossSearch } from "./pages/CrossSearch";
import { ReportDetail, ReportForm, ReportList } from "./pages/Reports";
import { Summary } from "./pages/Summary";
import { Organization } from "./pages/Organization";
import { Structure } from "./pages/Structure";
import { Institutions } from "./pages/Institutions";
import { Ranks } from "./pages/Ranks";
import { Analytics } from "./pages/Analytics";
import { Integrations } from "./pages/Integrations";
import { FoodStores } from "./pages/FoodStores";
import { UnitOverview, UnitsHome } from "./pages/UnitOverview";
import { ChangeRequests } from "./pages/ChangeRequests";
import { Tasks } from "./pages/Tasks";
import { DueSoon } from "./pages/DueSoon";
import { SystemHealth } from "./pages/SystemHealth";
import { DepartmentProfile } from "./pages/DepartmentProfile";
import { OrgSettings } from "./pages/OrgSettings";
import { OrgTree } from "./pages/OrgTree";
import { MyRecord } from "./pages/MyRecord";
import { StructureChanges } from "./pages/StructureChanges";
import { UserDetail, Users } from "./pages/Users";
import { Credentials } from "./pages/Credentials";
import { CredentialView } from "./pages/CredentialView";
import { Schedules } from "./pages/Schedules";
import { Verify } from "./pages/Verify";

export default function App() {
  const { me, loading } = useAuth();
  const location = useLocation();
  // Public: opened by scanning the QR code on an ID card or letter. Works whether or not anyone is signed in.
  const verifyMatch = /^\/verify\/([^/]+)\/?$/.exec(location.pathname);
  if (verifyMatch) return <Routes><Route path="verify/:code" element={<Verify />} /></Routes>;
  if (loading) return <main><Loading variant="cards" /></main>;
  if (!me) {
    if (location.pathname === "/reset") return <ResetPassword />;
    if (location.pathname === "/forgot") return <ForgotPassword />;
    if (location.pathname === "/recover") return <RecoverMfa />;
    if (location.pathname === "/offline-desk" && SHOW_OFFLINE_DESK) return <OfflineDesk />;
    return <Login />;
  }
  if (me.restrictions.includes("password_change")) return <ForcedPassword />;
  if (me.restrictions.includes("mfa_enrollment")) return <MfaEnrol />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="organization" element={<Organization />} />
        <Route path="structure" element={<Structure />} />
        <Route path="units" element={<UnitsHome />} />
        <Route path="units/:id" element={<UnitOverview />} />
        <Route path="units/:id/departments/:deptId" element={<DepartmentProfile />} />
        <Route path="org-settings" element={<OrgSettings />} />
        <Route path="change-requests" element={<ChangeRequests />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="due-soon" element={<DueSoon />} />
        <Route path="system-health" element={<SystemHealth />} />
        <Route path="food" element={<FoodStores />} />
        <Route path="institutions" element={<Institutions />} />
        <Route path="tree" element={<OrgTree />} />
        <Route path="structure-changes" element={<StructureChanges />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="integrations" element={<Integrations />} />
        <Route path="my-record" element={<MyRecord />} />
        <Route path="personnel" element={<PersonnelList />} />
        <Route path="personnel/new" element={<PersonnelForm />} />
        <Route path="personnel/import" element={<PersonnelImport />} />
        <Route path="attendance" element={<Attendance />} />
        <Route path="leave" element={<Leave />} />
        <Route path="promotion" element={<Promotion />} />
        <Route path="fitness" element={<Fitness />} />
        <Route path="weapons" element={<Weapons />} />
        <Route path="inventories" element={<Inventories />} />
        <Route path="vehicles" element={<Vehicles />} />
        <Route path="vehicles/:id" element={<VehicleDetail />} />
        <Route path="vehicle-log" element={<VehicleLog />} />
        <Route path="vehicle-tracking" element={<VehicleTracking />} />
        {/* Custody and the Occurrence Book are switched off on the server for now (CUSTODY_ENABLED); the pages stay built. */}
        {me?.features.custody === true && (
          <>
          <Route path="detention" element={<Detention />} />
          <Route path="occurrence-book" element={<OccurrenceBook />} />
          <Route path="shift-handover" element={<ShiftHandover />} />
          <Route path="custody-facilities" element={<CustodyFacilities />} />
          <Route path="custody-oversight" element={<DetentionOversight />} />
          <Route path="custody-incidents" element={<CustodyIncidents />} />
          <Route path="offline-desk" element={<OfflineDesk />} />
          </>
        )}
        <Route path="tax" element={<Tax />} />
        <Route path="tax-oversight" element={<TaxOversight />} />
        <Route path="personnel-report" element={<PersonnelReport />} />
        <Route path="credentials" element={<Credentials />} />
        <Route path="credentials/:id" element={<CredentialView />} />
        <Route path="schedules" element={<Schedules />} />
        <Route path="equipment" element={<Equipment />} />
        <Route path="equipment/:id" element={<EquipmentDetail />} />
        <Route path="holdings" element={<Holdings />} />
        <Route path="accountability" element={<AmmoAccountability />} />
        <Route path="ammo-control" element={<AmmoControl />} />
        <Route path="survivors" element={<Survivors />} />
        <Route path="payroll" element={<Payroll />} />
        <Route path="ammunition" element={<Ammunition />} />
        <Route path="ppe" element={<Ppe />} />
        <Route path="personnel/reporting-lines" element={<ReportingLines />} />
        <Route path="personnel/:id" element={<PersonnelDetail />} />
        <Route path="search" element={<CrossSearch />} />
        <Route path="combined" element={<Navigate to="/reports" replace />} />
        <Route path="reports" element={<ReportList />} />
        <Route path="reports/new" element={<ReportForm />} />
        <Route path="reports/:id/edit" element={<ReportForm />} />
        <Route path="reports/:id" element={<ReportDetail />} />
        <Route path="summary" element={<Summary />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="account" element={<Account />} />
        <Route path="logistics" element={<LogisticsHome />} />
        <Route path="logistics/stock/:id" element={<StockDetail />} />
        <Route path="logistics/assets/:id" element={<AssetDetail />} />
        <Route path="logistics/reconciliations/:id" element={<ReconDetail />} />
        <Route path="training" element={<TrainingHome />} />
        <Route path="training/records/:id" element={<TrainingRecordDetail />} />
        <Route path="ranks" element={<Ranks />} />
        <Route path="users" element={<Users />} />
        <Route path="users/import" element={<UsersBulk />} />
        <Route path="users/review" element={<AccessReview />} />
        <Route path="users/:id" element={<UserDetail />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
