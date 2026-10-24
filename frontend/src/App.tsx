import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { AuditLog } from "./pages/AuditLog";
import { Dashboard } from "./pages/Dashboard";
import { ForcedPassword, MfaEnrol } from "./pages/Enrol";
import { Login } from "./pages/Login";
import { ResetPassword } from "./pages/Reset";
import { Attendance } from "./pages/Attendance";
import { Ammunition } from "./pages/Ammunition";
import { Weapons } from "./pages/Weapons";
import { Holdings } from "./pages/Holdings";
import { AmmoAccountability } from "./pages/AmmoAccountability";
import { Survivors } from "./pages/Survivors";
import { Payroll } from "./pages/Payroll";
import { ReportingLines } from "./pages/ReportingLines";
import { PersonnelDetail, PersonnelForm, PersonnelImport, PersonnelList } from "./pages/Personnel";
import { AssetDetail, LogisticsHome, ReconDetail, StockDetail } from "./pages/Logistics";
import { TrainingHome, TrainingRecordDetail } from "./pages/Training";
import { Notifications } from "./pages/Notifications";
import { CrossSearch } from "./pages/CrossSearch";
import { CombinedReport } from "./pages/CombinedReport";
import { ReportDetail, ReportForm, ReportList } from "./pages/Reports";
import { Summary } from "./pages/Summary";
import { Organization } from "./pages/Organization";
import { Structure } from "./pages/Structure";
import { Institutions } from "./pages/Institutions";
import { Ranks } from "./pages/Ranks";
import { Analytics } from "./pages/Analytics";
import { Integrations } from "./pages/Integrations";
import { OrgTree } from "./pages/OrgTree";
import { StructureChanges } from "./pages/StructureChanges";
import { UserDetail, Users } from "./pages/Users";

export default function App() {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <main><Loading /></main>;
  if (!me) return location.pathname === "/reset" ? <ResetPassword /> : <Login />;
  if (me.restrictions.includes("password_change")) return <ForcedPassword />;
  if (me.restrictions.includes("mfa_enrollment")) return <MfaEnrol />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="organization" element={<Organization />} />
        <Route path="structure" element={<Structure />} />
        <Route path="institutions" element={<Institutions />} />
        <Route path="tree" element={<OrgTree />} />
        <Route path="structure-changes" element={<StructureChanges />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="integrations" element={<Integrations />} />
        <Route path="personnel" element={<PersonnelList />} />
        <Route path="personnel/new" element={<PersonnelForm />} />
        <Route path="personnel/import" element={<PersonnelImport />} />
        <Route path="attendance" element={<Attendance />} />
        <Route path="weapons" element={<Weapons />} />
        <Route path="holdings" element={<Holdings />} />
        <Route path="accountability" element={<AmmoAccountability />} />
        <Route path="survivors" element={<Survivors />} />
        <Route path="payroll" element={<Payroll />} />
        <Route path="ammunition" element={<Ammunition />} />
        <Route path="personnel/reporting-lines" element={<ReportingLines />} />
        <Route path="personnel/:id" element={<PersonnelDetail />} />
        <Route path="search" element={<CrossSearch />} />
        <Route path="combined" element={<CombinedReport />} />
        <Route path="reports" element={<ReportList />} />
        <Route path="reports/new" element={<ReportForm />} />
        <Route path="reports/:id/edit" element={<ReportForm />} />
        <Route path="reports/:id" element={<ReportDetail />} />
        <Route path="summary" element={<Summary />} />
        <Route path="notifications" element={<Notifications />} />
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
