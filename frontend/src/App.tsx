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
import { Ammunition } from "./pages/Ammunition";
import { Weapons } from "./pages/Weapons";
import { Inventories } from "./pages/Inventories";
import { Ppe } from "./pages/Ppe";
import { VehicleDetail, Vehicles } from "./pages/Vehicles";
import { Equipment, EquipmentDetail } from "./pages/Equipment";
import { Holdings } from "./pages/Holdings";
import { AmmoAccountability } from "./pages/AmmoAccountability";
import { AmmoControl } from "./pages/AmmoControl";
import { Survivors } from "./pages/Survivors";
import { Payroll } from "./pages/Payroll";
import { ReportingLines } from "./pages/ReportingLines";
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
import { DepartmentProfile } from "./pages/DepartmentProfile";
import { OrgSettings } from "./pages/OrgSettings";
import { OrgTree } from "./pages/OrgTree";
import { MyRecord } from "./pages/MyRecord";
import { StructureChanges } from "./pages/StructureChanges";
import { UserDetail, Users } from "./pages/Users";

export default function App() {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <main><Loading /></main>;
  if (!me) {
    if (location.pathname === "/reset") return <ResetPassword />;
    if (location.pathname === "/forgot") return <ForgotPassword />;
    if (location.pathname === "/recover") return <RecoverMfa />;
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
        <Route path="weapons" element={<Weapons />} />
        <Route path="inventories" element={<Inventories />} />
        <Route path="vehicles" element={<Vehicles />} />
        <Route path="vehicles/:id" element={<VehicleDetail />} />
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
        <Route path="users/:id" element={<UserDetail />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
