import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { EmptyState } from "../components/ui";
import { useI18n } from "../i18n";

/** Shortcut to the signed-in person's own personnel record. The record page and its access rules are unchanged. */
export function MyRecord() {
  const { me } = useAuth();
  const { t } = useI18n();
  if (me?.personnel_id) return <Navigate to={`/personnel/${me.personnel_id}`} replace />;
  return (
    <>
      <h1>{t("nav.myRecord")}</h1>
      <EmptyState icon="users" title={t("myrec.none")} />
    </>
  );
}
