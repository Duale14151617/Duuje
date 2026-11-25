import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { myPhotoUrl } from "../api/client";

/** Round avatar of the signed-in user: the official photo on their linked personnel record, else the default picture.
 *  Never throws and never shows a broken image: any load failure falls back to the default. */
export function Avatar({ size = 32 }: { size?: number }) {
  const { me } = useAuth();
  const src = myPhotoUrl(me?.personnel_id, me?.photo_v); // photo_v is set when there is an account picture or a personnel photo
  const [failed, setFailed] = useState<string | null>(null);
  const useDefault = !src || failed === src;
  return (
    <img className="avatar" src={useDefault ? "/avatar-default.png" : src} alt="" width={size} height={size}
         loading="lazy" decoding="async" onError={() => setFailed(src)} />
  );
}
