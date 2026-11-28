import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";
import { formatDay } from "../lib/format";
import { Notice } from "./ui";

/** Banner for people whose role touches pay, weapons, medical or personnel records but who have not turned on two-step sign-in.
 *  It cannot be dismissed (it goes away when two-step sign-in is on). With a deadline set on the server it says when it becomes mandatory. */
export function MfaPrompt() {
  const { me } = useAuth();
  const { t, lang } = useI18n();
  const here = useLocation().pathname;
  if (!me || !me.mfa_recommended || here === "/account") return null;
  return (
    <Notice kind="warn">
      <strong>{t("mfa.promptTitle")}</strong>{" "}
      {me.mfa_required_from ? t("mfa.promptDeadline", { date: formatDay(me.mfa_required_from, lang) }) : t("mfa.promptBody")}{" "}
      <Link to="/account">{t("mfa.promptAction")}</Link>
    </Notice>
  );
}
