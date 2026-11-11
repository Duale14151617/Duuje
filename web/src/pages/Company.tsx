import { NavLink, Navigate, Route, Routes, useParams } from "react-router-dom";
import { Status, useLoad } from "../hooks";
import { Icon } from "../icons";

const TAB_ICONS: Record<string, string> = { jobs: "briefcase", review: "clipboard", finance: "wallet", reports: "chart", customers: "customer", technicians: "wrench", branches: "pin", staff: "badge" };
import Branches from "./company/Branches";
import Staff from "./company/Staff";
import Customers from "./company/Customers";
import Technicians from "./company/Technicians";
import Jobs from "./company/Jobs";
import Review from "./company/Review";
import Finance from "./company/Finance";
import Reports from "./company/Reports";

export default function Company() {
  const { id } = useParams();
  const { data: c, error } = useLoad<any>(`/companies/${id}`);
  if (error) return <p className="error">{error}</p>;
  if (!c) return <p>Loading…</p>;
  const approved = c.verification === "Approved";
  return (
    <>
      <h1>{c.displayName} <Status value={c.verification} /></h1>
      {!approved && <div className="card">This company is <b>{c.verification}</b>. {c.verificationNote && <>Reviewer note: {c.verificationNote}. </>}Branches, staff, technicians and jobs unlock once it is approved.</div>}
      <nav className="row" style={{ marginBottom: 12 }}>
        {["jobs", "review", "finance", "reports", "customers", "technicians", "branches", "staff"].map((t) => (
          <NavLink key={t} to={`/companies/${id}/${t}`} className={({ isActive }) => (isActive ? "pill Active" : "pill")} style={{ padding: "6px 12px", textDecoration: "none", color: "inherit" }}><Icon name={TAB_ICONS[t]} size={16} />{t[0].toUpperCase() + t.slice(1)}</NavLink>
        ))}
      </nav>
      <Routes>
        <Route path="jobs" element={<Jobs companyId={id!} />} />
        <Route path="review" element={<Review companyId={id!} />} />
        <Route path="finance" element={<Finance companyId={id!} />} />
        <Route path="reports" element={<Reports companyId={id!} />} />
        <Route path="customers" element={<Customers companyId={id!} />} />
        <Route path="technicians" element={<Technicians companyId={id!} />} />
        <Route path="branches" element={<Branches companyId={id!} />} />
        <Route path="staff" element={<Staff companyId={id!} />} />
        <Route path="*" element={<Navigate to="jobs" replace />} />
      </Routes>
    </>
  );
}
