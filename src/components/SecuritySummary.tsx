import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import { formatDateTime } from "../lib/format";
import { Chip } from "./ui";

/** Account page: at-a-glance security state: two-step sign-in, backup codes, passkeys and the previous sign-in. */
export function SecuritySummary() {
  const { me } = useAuth();
  const { t, lang } = useI18n();
  if (!me) return null;
  const left = me.backup_codes_remaining ?? 0;
  const last = me.sign_in;
  return (
    <section className="card">
      <h2>{t("secsum.title")}</h2>
      <ul className="list">
        <li className="item">
          {t("secsum.mfa")}{" "}
          {me.mfa_enabled ? <Chip tone="ok">{t("secsum.on")}</Chip> : <Chip tone="warn">{t("secsum.off")}</Chip>}
        </li>
        {me.mfa_enabled && (
          <>
            <li className="item">
              {t("secsum.backup")}{" "}
              <Chip tone={left === 0 ? "bad" : left <= 2 ? "warn" : "ok"}>{left}</Chip>
            </li>
            <li className="item">{t("secsum.passkeys")} <Chip tone="draft">{me.passkey_count ?? 0}</Chip></li>
          </>
        )}
        <li className="item">
          {t("secsum.last")}{" "}
          {last
            ? <span>{formatDateTime(last.previous_at, lang)}{last.previous_ip ? <span className="muted"> · {last.previous_ip}</span> : null}</span>
            : <span className="muted">{t("secsum.firstEver")}</span>}
        </li>
        {last && last.failed_since > 0 && (
          <li className="item"><Chip tone="warn">{t("secsum.failed", { n: last.failed_since })}</Chip></li>
        )}
      </ul>
    </section>
  );
}
