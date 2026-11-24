import { PageHeader } from "../components/ui";
import { VehiclePositions } from "../components/VehiclePositions";
import { useI18n } from "../i18n";

/** Vehicle tracking: latest positions on the Puntland map, silent vehicles, route trails, zones and the daily movement report,
 *  manual and phone reports, and GPS trackers. All of it lives in VehiclePositions, which the vehicle detail page also uses. */
export function VehicleTracking() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("trk.title")} subtitle={t("trk.subtitle")} />
      <VehiclePositions heading={false} />
    </>
  );
}
