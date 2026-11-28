import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import { Notice } from "./ui";

/** Banner shown in the last days before a password reaches its age limit (PASSWORD_MAX_AGE_DAYS on the server). */
export function PasswordPrompt() {
  const { me } = useAuth();
  const { t } = useI18n();
  const here = useLocation().pathname;
  if (!me || !me.password_warn || me.password_days_left == null || here === "/account") return null;
  return (
    <Notice kind="warn">
      <strong>{t("pwage.title")}</strong> {t("pwage.body", { n: me.password_days_left })} <Link to="/account">{t("pwage.action")}</Link>
    </Notice>
  );
}
