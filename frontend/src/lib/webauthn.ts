/** Browser side of passkeys (WebAuthn): converts the server's JSON options for the browser API and the browser's answer back to JSON. */

export const passkeysSupported = (): boolean =>
  typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;

const toBytes = (b64url: string): Uint8Array => {
  const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
  const bin = atob(b64url.replace(/-/g, "+").replace(/_/g, "/") + pad);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
};
const toB64 = (buf: ArrayBuffer | null | undefined): string => {
  if (!buf) return "";
  let s = "";
  new Uint8Array(buf).forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

interface Desc { type: "public-key"; id: string; transports?: string[] }
type Json = Record<string, unknown>;

const descriptors = (list: Desc[] | undefined) =>
  (list ?? []).map((d) => ({ ...d, id: toBytes(d.id) }) as unknown as PublicKeyCredentialDescriptor);

/** Create a new passkey. Throws if the person cancels (NotAllowedError) or the device cannot. */
export async function createPasskey(options: Json): Promise<Json> {
  const o = options as unknown as { challenge: string; user: { id: string }; excludeCredentials?: Desc[] };
  const cred = (await navigator.credentials.create({
    publicKey: { ...(options as object), challenge: toBytes(o.challenge), user: { ...(options.user as object), id: toBytes(o.user.id) },
      excludeCredentials: descriptors(o.excludeCredentials) } as unknown as PublicKeyCredentialCreationOptions,
  })) as PublicKeyCredential | null;
  if (!cred) throw new Error("cancelled");
  const r = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id,
    response: { clientDataJSON: toB64(r.clientDataJSON), attestationObject: toB64(r.attestationObject),
      transports: typeof r.getTransports === "function" ? r.getTransports() : [] },
  };
}

/** Sign in or confirm with an existing passkey. */
export async function getPasskey(options: Json): Promise<Json> {
  const o = options as unknown as { challenge: string; allowCredentials?: Desc[] };
  const cred = (await navigator.credentials.get({
    publicKey: { ...(options as object), challenge: toBytes(o.challenge), allowCredentials: descriptors(o.allowCredentials) } as unknown as PublicKeyCredentialRequestOptions,
  })) as PublicKeyCredential | null;
  if (!cred) throw new Error("cancelled");
  const r = cred.response as AuthenticatorAssertionResponse;
  return { id: cred.id, response: { clientDataJSON: toB64(r.clientDataJSON), authenticatorData: toB64(r.authenticatorData), signature: toB64(r.signature) } };
}

/** True when the browser reported that the person dismissed the prompt rather than a real failure. */
export const wasCancelled = (e: unknown): boolean =>
  e instanceof DOMException ? e.name === "NotAllowedError" || e.name === "AbortError" : (e as Error)?.message === "cancelled";
