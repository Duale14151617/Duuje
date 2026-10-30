import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useI18n, type Key } from "../i18n";
import { MIN_QUERY, searchableModules, type SearchHit, type SearchModule } from "../lib/search";
import { PER_MODULE, runUniversalSearch } from "../lib/universalSearch";
import { Icon, type IconName } from "./Icon";
import { Chip } from "./ui";

const ICON: Record<SearchModule, IconName> = { personnel: "users", units: "building", vehicles: "truck", reports: "file", training: "cap", logistics: "box" };
const LABEL: Record<SearchModule, Key> = {
  personnel: "gs.personnel", units: "gs.units", vehicles: "gs.vehicles", reports: "gs.reports", training: "gs.training", logistics: "gs.logistics",
};
/** Rows per module on the "All" tab; a module's own tab shows everything fetched. */
const ALL_TAB = 4;

type Phase = "idle" | "loading" | "done";

const isTyping = (el: EventTarget | null) => {
  const n = el as HTMLElement | null;
  return !!n && (n.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(n.tagName));
};

/**
 * Universal search in the top bar. It asks the modules the signed-in user can already open (personnel, units, vehicles, reports,
 * training, logistics) through those modules' own list endpoints, so role permissions and unit scope are applied by the server
 * exactly as on each page. Press Ctrl/Cmd+K or "/" to focus it; on phones it opens as a full-width bar.
 */
export function GlobalSearch() {
  const { t, tr, name } = useI18n();
  const { can, reload } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const uid = useId();
  const modules = useMemo(() => searchableModules(can), [can]);
  const [q, setQ] = useState("");
  const [focused, setFocused] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [tab, setTab] = useState<"all" | SearchModule>("all");
  const [phase, setPhase] = useState<Phase>("idle");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [failed, setFailed] = useState<SearchModule[]>([]);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  const cache = useRef(new Map<string, Promise<unknown>>());
  const term = q.trim();
  const searching = term.length >= MIN_QUERY;
  const open = focused || mobile;

  const close = useCallback(() => {
    setFocused(false); setMobile(false); setQ(""); setHits([]); setPhase("idle"); setFailed([]); setTab("all");
    cache.current = new Map();
    seq.current += 1;
  }, []);

  // moving to another page ends the search
  useEffect(() => { close(); }, [pathname, close]);

  // shortcuts: Ctrl/Cmd+K anywhere, "/" when not typing in a field
  useEffect(() => {
    if (modules.length === 0) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (((e.ctrlKey || e.metaKey) && k === "k") || (k === "/" && !e.ctrlKey && !e.metaKey && !e.altKey && !isTyping(e.target))) {
        e.preventDefault();
        setMobile(window.matchMedia("(max-width: 767px)").matches);
        input.current?.focus();
        setFocused(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [modules.length]);

  useEffect(() => { if (mobile) input.current?.focus(); }, [mobile]);

  // debounced search; a newer query makes older answers irrelevant
  useEffect(() => {
    if (!searching) { seq.current += 1; setPhase("idle"); setHits([]); setFailed([]); return; }
    const mine = ++seq.current;
    setPhase("loading");
    const timer = setTimeout(() => {
      void runUniversalSearch(term, modules, { t, tr, name, can, cache: cache.current }).then((r) => {
        if (mine !== seq.current) return;
        setHits(r.hits); setFailed(r.failed); setActive(0); setPhase("done");
        if (r.signedOut) void reload();
      });
    }, 250);
    return () => clearTimeout(timer);
    // t/name/can change identity on language or session change, which should re-run the search
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [term, searching, modules, t, name, can]);

  const counts = useMemo(() => {
    const c: Partial<Record<SearchModule, number>> = {};
    for (const h of hits) c[h.module] = (c[h.module] ?? 0) + 1;
    return c;
  }, [hits]);
  const present = modules.filter((m) => (counts[m] ?? 0) > 0);
  const shownTab = tab === "all" || present.includes(tab) ? tab : "all";
  const groups = (shownTab === "all" ? present : [shownTab]).map((m) => ({
    module: m, rows: hits.filter((h) => h.module === m).slice(0, shownTab === "all" ? ALL_TAB : PER_MODULE),
  }));
  const flat = groups.flatMap((g) => g.rows);
  const activeIdx = Math.min(active, Math.max(0, flat.length - 1));
  const optId = (i: number) => `${uid}-opt-${i}`;

  const go = (h: SearchHit) => { navigate(h.to); close(); input.current?.blur(); };

  const viewAll = (m: SearchModule): string => {
    const enc = encodeURIComponent(term);
    switch (m) {
      case "personnel": return can("search.cross_service") ? `/search?q=${enc}` : `/personnel?q=${enc}`;
      case "vehicles": return `/vehicles?q=${enc}`;
      case "units": return "/units";
      case "reports": return "/reports";
      case "training": return "/training";
      default: return "/logistics";
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (flat.length === 0) return;
      e.preventDefault();
      setActive((activeIdx + (e.key === "ArrowDown" ? 1 : -1) + flat.length) % flat.length);
    } else if (e.key === "Enter") {
      if (flat[activeIdx]) { e.preventDefault(); go(flat[activeIdx]); }
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (q) { setQ(""); } else { close(); input.current?.blur(); }
    }
  };

  if (modules.length === 0) return null;

  const popOpen = open;
  const listId = `${uid}-list`;
  const status =
    phase === "loading" ? t("gs.searching")
    : phase === "done" ? t("gs.resultsCount", { count: hits.length }) : "";

  return (
    <div className={`gs${mobile ? " open" : ""}`} ref={root} role="search" aria-label={t("gs.label")}
         onBlur={(e) => { if (!root.current?.contains(e.relatedTarget as Node | null)) { setFocused(false); if (mobile && !q) setMobile(false); } }}>
      <button type="button" className="icon-btn gs-toggle" aria-label={t("gs.open")} onClick={() => setMobile(true)}><Icon name="search" size={18} /></button>
      <div className="gs-bar">
        <Icon name="search" size={18} />
        <input ref={input} type="search" value={q} role="combobox" aria-expanded={popOpen} aria-controls={listId} aria-autocomplete="list"
               aria-activedescendant={popOpen && flat.length > 0 ? optId(activeIdx) : undefined} aria-label={t("gs.label")}
               placeholder={t("gs.placeholder")} autoComplete="off" spellCheck={false}
               onChange={(e) => setQ(e.target.value)} onFocus={() => setFocused(true)} onKeyDown={onKeyDown} />
        <span className="gs-kbd" aria-hidden="true">Ctrl K</span>
        <button type="button" className="icon-btn gs-close" aria-label={t("gs.close")} onClick={() => { close(); input.current?.blur(); }}><Icon name="close" size={18} /></button>
      </div>
      <p className="sr-only" role="status" aria-live="polite">{status}</p>

      {popOpen && (
        <div className="gs-pop" onMouseDown={(e) => { if ((e.target as HTMLElement).closest("button") === null) e.preventDefault(); }}>
          {searching && phase === "done" && present.length > 1 && (
            <div className="gs-tabs" role="group" aria-label={t("gs.filterBy")}>
              <button type="button" className="gs-tab" aria-pressed={shownTab === "all"} onClick={() => setTab("all")}>{t("gs.all")}<span className="gs-count">{hits.length}</span></button>
              {present.map((m) => (
                <button key={m} type="button" className="gs-tab" aria-pressed={shownTab === m} onClick={() => setTab(m)}>
                  {t(LABEL[m])}<span className="gs-count">{counts[m]}</span>
                </button>
              ))}
            </div>
          )}

          {!searching && (
            <div className="gs-msg"><strong>{t("gs.hintTitle")}</strong>{t("gs.hintBody", { modules: modules.map((m) => t(LABEL[m]).toLowerCase()).join(", ") })}</div>
          )}
          {searching && phase === "loading" && hits.length === 0 && <div className="gs-msg" role="status">{t("gs.searching")}</div>}
          {searching && phase === "done" && hits.length === 0 && (
            <div className="gs-msg">
              <strong>{failed.length > 0 ? t("gs.unavailable") : t("gs.noneTitle", { q: term })}</strong>
              {failed.length > 0 ? t("gs.unavailableBody") : t("gs.noneBody")}
            </div>
          )}

          {flat.length > 0 && (
            <div id={listId} role="listbox" aria-label={t("gs.results")}>
              {groups.map((g) => (
                <div className="gs-group" role="group" aria-label={t(LABEL[g.module])} key={g.module}>
                  <h3 aria-hidden="true">{t(LABEL[g.module])}</h3>
                  <ul className="gs-list" role="presentation">
                    {g.rows.map((h) => {
                      const i = flat.indexOf(h);
                      return (
                        <li key={h.id} role="presentation">
                          <a role="option" id={optId(i)} href={h.to} aria-selected={i === activeIdx} className="gs-opt"
                             onMouseMove={() => setActive(i)} onClick={(e) => { e.preventDefault(); go(h); }}>
                            <span className="ico" aria-hidden="true"><Icon name={ICON[h.module]} size={16} /></span>
                            <span className="gs-opt-text">
                              <span className="gs-opt-title">{h.title}</span>
                              <span className="gs-opt-sub">{h.subtitle}</span>
                            </span>
                            {h.badge ? <Chip>{h.badge}</Chip> : null}
                          </a>
                        </li>
                      );
                    })}
                  </ul>
                  {shownTab !== "all" || (counts[g.module] ?? 0) > ALL_TAB ? (
                    <a className="gs-all" href={viewAll(g.module)} onClick={(e) => { e.preventDefault(); navigate(viewAll(g.module)); }}>{t("gs.viewAll", { module: t(LABEL[g.module]).toLowerCase() })}</a>
                  ) : null}
                </div>
              ))}
            </div>
          )}
          {failed.length > 0 && hits.length > 0 && <div className="gs-foot" role="status">{t("gs.partial")}</div>}
          {searching && <div className="gs-foot">{t("gs.scopeNote")}</div>}
        </div>
      )}
    </div>
  );
}
