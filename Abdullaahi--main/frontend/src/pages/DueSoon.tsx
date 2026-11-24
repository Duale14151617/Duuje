import { Link } from "react-router-dom";
import { useFetch } from "../api/useFetch";
import { Chip, EmptyState, ErrorNotice, Loading, PageHeader } from "../components/ui";
import { useI18n, type Key } from "../i18n";
import { formatDay } from "../lib/format";

interface Item { id: string; label: string; due_on: string; overdue: boolean; note?: string; unit_en: string; unit_so: string }
interface Group { kind: string; count: number; items: Item[]; link: string }
interface Due { groups: Group[]; total: number }

/** Dated items that are close or already past: ID cards, vehicle services, court dates and remand orders. */
export function DueSoon() {
  const { t, lang } = useI18n();
  const due = useFetch<Due>("/due-soon/");
  const groups = (due.data?.groups ?? []).filter((g) => g.count > 0);
  return (
    <>
      <PageHeader title={t("due.title")} subtitle={t("due.intro")} />
      <ErrorNotice error={due.error} />
      {due.loading && !due.data ? <Loading variant="table" /> : null}
      {due.data && groups.length === 0 && <EmptyState icon="check" title={t("due.none")} hint={t("due.noneHint")} />}
      {groups.map((g) => (
        <section key={g.kind} className="card">
          <h2>{t(`due.kind.${g.kind}` as Key)} <Chip tone={g.items.some((i) => i.overdue) ? "bad" : "warn"}>{g.count}</Chip></h2>
          <ul className="list">
            {g.items.map((i) => (
              <li key={`${g.kind}-${i.id}`} className="item row row-between">
                <span><Link to={g.link}><b>{i.label}</b></Link> <span className="muted">· {lang === "so" ? i.unit_so || i.unit_en : i.unit_en}</span>
                  {i.note ? <span className="muted"> · {t(`due.note.${i.note}` as Key)}</span> : null}</span>
                <span className={i.overdue ? "due-overdue" : "muted"}>{i.overdue ? t("due.overdue", { date: formatDay(i.due_on, lang) }) : t("due.on", { date: formatDay(i.due_on, lang) })}</span>
              </li>
            ))}
          </ul>
          {g.count > g.items.length && <p className="muted">{t("review.more", { n: g.count - g.items.length })}</p>}
        </section>
      ))}
    </>
  );
}
