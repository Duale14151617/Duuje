import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { useI18n, type Key } from "../i18n";
import { Icon } from "./Icon";
import { ThemeToggle } from "../theme/ThemeToggle";

export function Layout() {
  const { me, can, logout } = useAuth();
  const { t, lang, setLang, name } = useI18n();

  const location = useLocation();
  const unread = useFetch<{ count: number }>("/notifications/unread-count/", { at: location.pathname });
  const count = unread.data?.count ?? 0;
  const items: { to: string; label: Key; show: boolean }[] = [
    { to: "/", label: "nav.dashboard", show: can("dashboard.view") },
    { to: "/organization", label: "nav.organization", show: can("org.view") },
    { to: "/structure", label: "nav.structure", show: can("org.view") },
    { to: "/tree", label: "nav.tree", show: can("org.view") },
    { to: "/structure-changes", label: "nav.structureChanges", show: can("org.structure_propose") || can("org.structure_approve") },
    { to: "/personnel", label: "nav.personnel", show: can("personnel.view") },
    { to: "/reports", label: "nav.reports", show: can("reports.view") },
    { to: "/summary", label: "nav.summary", show: can("reports.summary") },
    { to: "/logistics", label: "nav.logistics", show: ["logistics.view", "logistics.restricted", "logistics.configure", "logistics.approve", "logistics.restricted_approve", "logistics.report"].some(can) },
    { to: "/training", label: "nav.training", show: ["training.view", "training.configure", "training.report"].some(can) },
    { to: "/analytics", label: "nav.analytics", show: can("analytics.view") },
    { to: "/ranks", label: "nav.ranks", show: can("ranks.view") },
    { to: "/users", label: "nav.users", show: can("users.view") },
    { to: "/integrations", label: "nav.integrations", show: can("integrations.view") },
    { to: "/audit", label: "nav.audit", show: can("audit.view") },
    { to: "/notifications", label: "nav.notifications", show: true },
  ];

  async function switchLang() {
    const next = lang === "en" ? "so" : "en";
    setLang(next);
    try { await api("/auth/me/", { method: "PATCH", body: { preferred_language: next } }); } catch { /* preference only */ }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand" style={{ display: "inline-flex", alignItems: "center", gap: ".5rem" }}>
          <img src="/defence-force.jpg" alt="Puntland Defence Force emblem" width={32} height={32} style={{ borderRadius: 4 }} />
          {t("app.name")}
        </span>
        <div className="topbar-actions">
          <ThemeToggle />
          <button onClick={() => void switchLang()} lang={lang === "en" ? "so" : "en"}>{t("lang.other")}</button>
          <button className="icon-btn" onClick={() => void logout()} aria-label={t("common.signOut")} title={t("common.signOut")}><Icon name="logout" size={18} /></button>
        </div>
      </header>
      {import.meta.env.VITE_DEMO === "1" && <div className="demo-banner" role="note">{t("demo.banner")}</div>}
      <div className="scope-strip" aria-label={t("scope.label")}>
        {me && me.assignments.length > 0 ? (
          <ul>
            {me.assignments.map((a) => (
              <li key={a.id}>
                <strong>{name(a.role)}</strong>
                <span className="path">
                  <span>{name(a.org_unit)}</span>
                  <span>{a.branch ? name(a.branch) : t("scope.allBranches")}</span>
                </span>
                {a.valid_until && <div className="muted">{t("scope.until", { date: a.valid_until })}</div>}
              </li>
            ))}
          </ul>
        ) : (
          <div className="none">{t("users.noAssignments")}</div>
        )}
      </div>
      <nav className="nav">
        {items.filter((i) => i.show).map((i) => (
          <NavLink key={i.to} to={i.to} end={i.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
            {t(i.label)}{i.to === "/notifications" && count > 0 ? ` (${count})` : ""}
          </NavLink>
        ))}
      </nav>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
