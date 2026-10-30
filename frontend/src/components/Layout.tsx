import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { useI18n, type Key } from "../i18n";
import { GlobalSearch } from "./GlobalSearch";
import { Icon, type IconName } from "./Icon";
import { useMedia } from "./useMedia";
import { InstallButton } from "../pwa/install";
import { ThemeToggle } from "../theme/ThemeToggle";

const SIDEBAR_KEY = "armyhq.sidebar";
const GROUPS_KEY = "armyhq.navgroups"; // names of the sidebar sections the user has folded away

type NavItem = { to: string; label: Key; icon: IconName; show: boolean };

/** Which section each page sits in; sections with no visible page are not drawn. `title` is absent for the top block. */
const NAV_SECTIONS: { key: string; title?: Key; to: string[] }[] = [
  { key: "top", to: ["/", "/notifications"] },
  { key: "units", title: "nav.group.units", to: ["/organization", "/institutions", "/structure", "/tree", "/structure-changes", "/units", "/change-requests"] },
  { key: "people", title: "nav.group.people", to: ["/personnel", "/search", "/attendance", "/training", "/ranks"] },
  { key: "pay", title: "nav.group.pay", to: ["/payroll", "/survivors"] },
  { key: "reporting", title: "nav.group.reporting", to: ["/combined", "/reports", "/summary", "/analytics", "/tasks"] },
  { key: "logistics", title: "nav.group.logistics", to: ["/logistics", "/ammunition", "/weapons", "/vehicles", "/holdings", "/accountability", "/food"] },
  { key: "admin", title: "nav.group.admin", to: ["/users", "/integrations", "/audit"] },
];

export function Layout() {
  const { me, can, logout } = useAuth();
  const { t, lang, setLang, name } = useI18n();

  const location = useLocation();
  const unread = useFetch<{ count: number }>("/notifications/unread-count/", { at: location.pathname });
  const count = unread.data?.count ?? 0;
  const items: NavItem[] = [
    { to: "/", icon: "grid", label: "nav.dashboard", show: can("dashboard.view") },
    { to: "/organization", icon: "building", label: "nav.organization", show: can("org.view") },
    { to: "/institutions", icon: "map", label: "nav.institutions", show: true },
    { to: "/structure", icon: "layers", label: "nav.structure", show: can("org.view") },
    { to: "/tree", icon: "tree", label: "nav.tree", show: can("org.view") },
    { to: "/structure-changes", icon: "swap", label: "nav.structureChanges", show: can("org.structure_propose") || can("org.structure_approve") },
    { to: "/personnel", icon: "users", label: "nav.personnel", show: can("personnel.view") || can("personnel.view_team") },
    { to: "/search", icon: "search", label: "nav.search", show: can("search.cross_service") },
    { to: "/combined", icon: "list", label: "nav.combined", show: can("reports.combined") },
    { to: "/reports", icon: "file", label: "nav.reports", show: can("reports.view") },
    { to: "/summary", icon: "list", label: "nav.summary", show: can("reports.summary") },
    { to: "/logistics", icon: "box", label: "nav.logistics", show: ["logistics.view", "logistics.restricted", "logistics.configure", "logistics.approve", "logistics.restricted_approve", "logistics.report"].some(can) },
    { to: "/ammunition", icon: "box", label: "nav.ammunition", show: can("logistics.restricted") },
    { to: "/weapons", icon: "lock", label: "nav.weapons", show: can("weapons.view") },
    { to: "/vehicles", icon: "box", label: "nav.vehicles", show: can("vehicles.view") },
    { to: "/holdings", icon: "users", label: "nav.holdings", show: can("weapons.view") },
    { to: "/accountability", icon: "list", label: "nav.accountability", show: can("weapons.view") },
    { to: "/payroll", icon: "list", label: "nav.payroll", show: can("payroll.view") },
    { to: "/survivors", icon: "users", label: "nav.survivors", show: can("survivor.view") },
    { to: "/attendance", icon: "check", label: "nav.attendance", show: can("attendance.view") },
    { to: "/units", icon: "building", label: "nav.units", show: can("org.view") },
    { to: "/change-requests", icon: "swap", label: "nav.changeRequests", show: can("changes.propose") || can("changes.approve") },
    { to: "/tasks", icon: "check", label: "nav.tasks", show: can("tasks.view") },
    { to: "/food", icon: "box", label: "nav.food", show: can("food.view") },
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
  const isTablet = useMedia("(max-width: 959px)");
  const [pref, setPref] = useState<"collapsed" | "expanded" | null>(() => {
    try { const v = localStorage.getItem(SIDEBAR_KEY); return v === "collapsed" || v === "expanded" ? v : null; } catch { return null; }
  });
  const collapsed = isTablet || pref === "collapsed"; // below 960px always the icon rail; from 960px the full sidebar unless the user collapsed it
  const [open, setOpen] = useState(false);
  const [folded, setFolded] = useState<string[]>(() => {
    try { const v: unknown = JSON.parse(localStorage.getItem(GROUPS_KEY) ?? "[]"); return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []; } catch { return []; }
  });
  const saveFolded = (next: string[]) => {
    setFolded(next);
    try { localStorage.setItem(GROUPS_KEY, JSON.stringify(next)); } catch { /* preference only */ }
  };
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
      const f = Array.from(sidebar.current.querySelectorAll<HTMLElement>("a[href], button:not([disabled])")).filter((el) => !el.closest("[hidden]")); // links inside a folded section cannot take focus
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

  // the icon rail has no room for section headings, so it shows every page with a thin divider between sections
  const rail = collapsed && !isMobile;
  const isHere = (to: string) => (to === "/" ? location.pathname === "/" : location.pathname === to || location.pathname.startsWith(`${to}/`));
  const placed = new Set(NAV_SECTIONS.flatMap((sec) => sec.to));
  const sections = [
    ...NAV_SECTIONS.map((sec) => ({ ...sec, items: sec.to.map((to) => items.find((i) => i.to === to)).filter((i): i is NavItem => !!i && i.show) })),
    // a page added to `items` but not yet to a section still appears, in a heading-less block at the end
    { key: "other", title: undefined, to: [] as string[], items: items.filter((i) => i.show && !placed.has(i.to)) },
  ].filter((sec) => sec.items.length > 0);
  const hereKey = sections.find((sec) => sec.items.some((i) => isHere(i.to)))?.key;
  // arriving at a page inside a folded section (a dashboard link, the back button) opens that section
  useEffect(() => {
    if (hereKey && folded.includes(hereKey)) saveFolded(folded.filter((k) => k !== hereKey));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hereKey, location.pathname]);

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
            <img src="/puntland-flag.svg" alt="Puntland flag" width={36} height={24} style={{ borderRadius: 3, boxShadow: "0 0 0 1px rgba(198,161,91,.7)" }} />
            <span className="brand-text">{t("app.name")}</span>
          </span>
        </div>
        <GlobalSearch />
        <div className="topbar-actions">
          <InstallButton />
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
            <img src="/puntland-flag.svg" alt="" width={36} height={24} style={{ borderRadius: 3, boxShadow: "0 0 0 1px rgba(198,161,91,.7)" }} />
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
          {sections.map((sec) => {
            const isOpen = rail || !sec.title || !folded.includes(sec.key);
            return (
              <div className="nav-group" key={sec.key}>
                {sec.title && !rail && (
                  <button type="button" className="nav-group-head" aria-expanded={isOpen} aria-controls={`nav-g-${sec.key}`}
                          onClick={() => saveFolded(isOpen ? [...folded, sec.key] : folded.filter((k) => k !== sec.key))}>
                    <span>{t(sec.title)}</span>
                    <Icon name="arrow" size={14} />
                  </button>
                )}
                <div id={`nav-g-${sec.key}`} hidden={!isOpen}>
                  {sec.items.map((i) => {
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
                </div>
              </div>
            );
          })}
        </nav>
      </div>
      {tip && <div className="nav-tip" role="presentation" style={{ top: tip.top }}>{tip.text}</div>}
      <main>
        <Outlet />
      </main>
      <footer className="muted small" style={{ textAlign: "center", padding: "1rem" }}>{t("app.name")} · Pilot build</footer>
    </div>
  );
}
