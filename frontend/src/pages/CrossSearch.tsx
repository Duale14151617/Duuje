import { useState } from "react";
import { Link } from "react-router-dom";
import type { Person } from "../api/types";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, Loading } from "../components/ui";
import { useI18n, type Key } from "../i18n";

interface SearchResult { counts: Record<string, number>; total: number; truncated: boolean; results: Person[] }

/** One query over every service the user is authorised for (every service). The server applies the same scope as the personnel list. */
export function CrossSearch() {
  const { t, name } = useI18n();
  const [q, setQ] = useState("");
  const term = q.trim();
  const found = useFetch<SearchResult>(term.length >= 2 ? "/personnel/search/" : null, { q: term });
  const data = term.length >= 2 ? found.data : null;

  return (
    <>
      <h1>{t("srch.title")}</h1>
      <p className="muted">{t("srch.hint")}</p>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("pers.search")} aria-label={t("pers.search")}
             style={{ width: "100%", marginBottom: "1rem" }} />
      <ErrorNotice error={term.length >= 2 ? found.error : null} />
      {term.length >= 2 && found.loading && !data ? <Loading /> : null}
      {data && (
        <>
          <p>
            {Object.entries(data.counts).map(([code, n]) => <Chip key={code} tone="draft">{code} · {n}</Chip>)}{" "}
            {data.truncated && <span className="muted">{t("srch.truncated")}</span>}
          </p>
          {data.total === 0 && <p>{t("srch.none")}</p>}
          <ul className="list">
            {data.results.map((p) => (
              <li key={p.id} className="item">
                <Link to={`/personnel/${p.id}`}><b>{p.full_name}</b></Link>
                <div className="muted">
                  {name(p.branch)} · {name(p.rank)} · {name(p.org_unit)} · {p.service_number ?? "-"} · {t(`pstatus.${p.status}` as Key)}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
