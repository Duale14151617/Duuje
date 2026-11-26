import { Link } from "react-router-dom";
import type { AccessReviewData } from "../api/types";
import { useFetch } from "../api/useFetch";
import { Chip, ErrorNotice, formatDate, Loading, Notice } from "../components/ui";
import { useI18n } from "../i18n";

/** Most urgent first. `tone` colours the count; global_access is information, not a problem. */
const ORDER: { code: string; tone: string }[] = [
  { code: "few_admins", tone: "bad" }, { code: "leaver_active", tone: "bad" }, { code: "privileged_no_mfa", tone: "bad" }, { code: "temp_expired", tone: "warn" },
  { code: "never_signed_in", tone: "warn" }, { code: "dormant", tone: "warn" }, { code: "no_role", tone: "warn" },
  { code: "ending_soon", tone: "warn" }, { code: "email_unverified", tone: "warn" }, { code: "locked", tone: "warn" },
  { code: "global_access", tone: "neutral" },
];

/** Who needs a human decision: dormant or never-used logins, privileged roles without MFA, expired temporary passwords ... */
export function AccessReview() {
  const { t, tr, lang } = useI18n();
  const review = useFetch<AccessReviewData>("/users/access-review/");
  const d = review.data;
  return (
    <>
      <p><Link to="/users">{t("common.back")}</Link></p>
      <h1>{t("review.title")}</h1>
      <p>{t("review.intro")}</p>
      <ErrorNotice error={review.error} />
      {review.loading && !d ? <Loading /> : null}
      {d && (
        <>
          <p className="muted">{t("review.generated", { date: formatDate(d.generated_at, lang), users: d.users, active: d.active_users })}</p>
          {d.needs_attention === 0 && <Notice>{t("review.clear")}</Notice>}
          {ORDER.map(({ code, tone }) => {
            const f = d.findings[code];
            if (!f || f.count === 0) return null;
            return (
              <section key={code} className="card">
                <h2>{tr(`review.f.${code}`) ?? code} <Chip tone={tone}>{f.count}</Chip></h2>
                <p className="muted">{tr(`review.do.${code}`)}</p>
                {code === "few_admins"
                  ? <p><b>{t("review.adminsNow", { n: f.items[0] })}</b></p>
                  : <ul className="list">{f.items.map((i) => <li key={i} className="item">{i}</li>)}</ul>}
                {f.count > f.items.length && <p className="muted">{t("review.more", { n: f.count - f.items.length })}</p>}
              </section>
            );
          })}
        </>
      )}
    </>
  );
}
