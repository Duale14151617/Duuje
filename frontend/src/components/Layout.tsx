import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { useI18n, type Key } from "../i18n";
import { Icon, type IconName } from "./Icon";
import { useMedia } from "./useMedia";
import { ThemeToggle } from "../theme/ThemeToggle";

const SIDEBAR_KEY = "armyhq.sidebar";

export function Layout() {
  const { me, can, logout } = useAuth();
  const { t, lang, setLang, name } = useI18n();

  const location = useLocation();
  const unread = useFetch<{ count: number }>("/notifications/unread-count/", { at: location.pathname });
  const count = unread.data?.count ?? 0;
  const items: { to: string; label: Key; icon: IconName; show: boolean }[] = [
    { to: "/", icon: "grid", label: "nav.dashboard", show: can("dashboard.view") },
    { to: "/organization", icon: "building", label: "nav.organization", show: can("org.view") },
    { to: "/institutions", icon: "map", label: "nav.institutions", show: true },
    { to: "/structure", icon: "layers", label: "nav.structure", show: can("org.view") },
    { to: "/tree", icon: "tree", label: "nav.tree", show: can("org.view") },
    { to: "/structure-changes", icon: "swap", label: "nav.structureChanges", show: can("org.structure_propose") || can("org.structure_approve") },
    { to: "/personnel", icon: "users", label: "nav.personnel", show: can("personnel.view") },
    { to: "/reports", icon: "file", label: "nav.reports", show: can("reports.view") },
    { to: "/summary", icon: "list", label: "nav.summary", show: can("reports.summary") },
    { to: "/logistics", icon: "box", label: "nav.logistics", show: ["logistics.view", "logistics.restricted", "logistics.configure", "logistics.approve", "logistics.restricted_approve", "logistics.report"].some(can) },
    { to: "/training", icon: "cap", label: "nav.training", show: ["training.view", "training.configure", "training.report"].some(can) },
    { to: "/analytics", icon: "activity", label: "nav.analytics", show: can("analytics.view") },
    { to: "/ranks", icon: "award", label: "nav.ranks", show: can("ranks.view") },
    { to: "/users", icon: "lock", label: "nav.users", show: can("users.view") },
    { to: "/integrations", icon: "plug", label: "nav.integrations", show: can("integrations.view") },
    { to: "/audit", icon: "check", label: "nav.audit", show: can("audit.view") },
    { to: "/notifications", icon: "bell", label: "nav.notifications", show: true },
  ];

  // ---- responsive sidebar: drawer < 768px, persistent sidebar/rail >= 768px ----
  const isMobile = useMedia("(max-width: 767px)");
  const isTablet = useMedia("(max-width: 1023px)");
  const [pref, setPref] = useState<"collapsed" | "expanded" | null>(() => {
    try { const v = localStorage.getItem(SIDEBAR_KEY); return v === "collapsed" || v === "expanded" ? v : null; } catch { return null; }
  });
  const collapsed = pref ? pref === "collapsed" : isTablet; // no saved choice: rail on tablets, full sidebar on desktop
  const [open, setOpen] = useState(false);
  const drawerOpen = open && isMobile;
  const menuBtn = useRef<HTMLButtonElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{ text: string; top: number } | null>(null);

  const closeDrawer = useCallback((restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) menuBtn.current?.focus();
  }, []);
  const toggleCollapsed = () => {
    const next = collapsed ? "expanded" : "collapsed";
    setPref(next);
    setTip(null);
    try { localStorage.setItem(SIDEBAR_KEY, next); } catch { /* preference only */ }
  };

  // close after any navigation (link tap, back/forward) and when the viewport grows past the drawer breakpoint
  useEffect(() => { setOpen(false); }, [location.pathname]);
  useEffect(() => { if (!isMobile) setOpen(false); }, [isMobile]);

  // while the drawer is open: lock background scroll, move focus in, Escape closes, Tab stays inside
  useEffect(() => {
    if (!drawerOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); closeDrawer(true); return; }
      if (e.key !== "Tab" || !sidebar.current) return;
      const f = Array.from(sidebar.current.querySelectorAll<HTMLElement>("a[href], button:not([disabled])"));
      if (f.length === 0) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = prev; document.removeEventListener("keydown", onKey); };
  }, [drawerOpen, closeDrawer]);

  const showTip = (text: string) => (e: { currentTarget: HTMLElement }) => {
    if (!collapsed || isMobile) return;
    const r = e.currentTarget.getBoundingClientRect();
    setTip({ text, top: r.top + r.height / 2 });
  };

  async function switchLang() {
    const next = lang === "en" ? "so" : "en";
    setLang(next);
    try { await api("/auth/me/", { method: "PATCH", body: { preferred_language: next } }); } catch { /* preference only */ }
  }

  return (
    <div className={`shell${collapsed ? " sb-collapsed" : ""}`}>
      <header className="topbar">
        <div className="topbar-start">
          <button ref={menuBtn} type="button" className="icon-btn menu-btn" onClick={() => setOpen(true)}
                  aria-label={t("nav.open")} aria-expanded={drawerOpen} aria-controls="app-sidebar">
            <Icon name="menu" size={20} />
          </button>
          <span className="brand" style={{ display: "inline-flex", alignItems: "center", gap: ".5rem" }}>
            <img src="/defence-force.jpg" alt="Puntland Defence Force emblem" width={32} height={32} style={{ borderRadius: 4 }} />
            {t("app.name")}
          </span>
        </div>
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
      {drawerOpen && <button type="button" className="sidebar-backdrop" tabIndex={-1} aria-hidden="true" onClick={() => closeDrawer()} />}
      <div id="app-sidebar" ref={sidebar} className={`sidebar${drawerOpen ? " open" : ""}`}
           role={drawerOpen ? "dialog" : undefined} aria-modal={drawerOpen ? true : undefined} aria-label={drawerOpen ? t("nav.label") : undefined}>
        <div className="nav-head">
          <span className="nav-brand">
            <img src="/defence-force.jpg" alt="" width={32} height={32} style={{ borderRadius: 4 }} />
            {t("app.name")}
          </span>
          <button ref={closeBtn} type="button" className="icon-btn nav-close" onClick={() => closeDrawer(true)} aria-label={t("nav.close")}>
            <Icon name="close" size={20} />
          </button>
          <button type="button" className="icon-btn nav-toggle" onClick={toggleCollapsed} aria-expanded={!collapsed}
                  aria-controls="app-nav" aria-label={collapsed ? t("nav.expand") : t("nav.collapse")}
                  onMouseEnter={showTip(collapsed ? t("nav.expand") : t("nav.collapse"))} onMouseLeave={() => setTip(null)}
                  onFocus={showTip(collapsed ? t("nav.expand") : t("nav.collapse"))} onBlur={() => setTip(null)}>
            <Icon name={collapsed ? "chevronsRight" : "chevronsLeft"} size={18} />
          </button>
        </div>
        <nav id="app-nav" className="nav" aria-label={t("nav.label")}>
          {items.filter((i) => i.show).map((i) => {
            const label = `${t(i.label)}${i.to === "/notifications" && count > 0 ? ` (${count})` : ""}`;
            return (
              <NavLink key={i.to} to={i.to} end={i.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}
                       data-unread={i.to === "/notifications" && count > 0 ? "" : undefined}
                       onClick={() => setOpen(false)}
                       onMouseEnter={showTip(label)} onMouseLeave={() => setTip(null)} onFocus={showTip(label)} onBlur={() => setTip(null)}>
                <Icon name={i.icon} size={20} />
                <span className="nav-label">{label}</span>
              </NavLink>
            );
          })}
        </nav>
      </div>
      {tip && <div className="nav-tip" role="presentation" style={{ top: tip.top }}>{tip.text}</div>}
      <main>
        <Outlet />
      </main>
      <footer className="muted small" style={{ textAlign: "center", padding: "1rem" }}>ARMY HQ · Pilot build</footer>
    </div>
  );
}
