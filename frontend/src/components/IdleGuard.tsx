import { useCallback, useEffect, useRef, useState } from "react";
import { getLastApiAt } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n";

const ACTIVITY_KEY = "hq.lastActivity";   // shared between tabs so working in one tab keeps the others signed in
export const IDLE_NOTICE_KEY = "hq.idleSignedOut"; // read by the sign-in page to say why the person was signed out
const PING_AFTER_MS = 60_000;             // tell the server about activity at most once a minute
const ABSOLUTE_WARN_S = 300;

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const readShared = (): number => { try { return Number(localStorage.getItem(ACTIVITY_KEY)) || 0; } catch { return 0; } };
const writeShared = (v: number) => { try { localStorage.setItem(ACTIVITY_KEY, String(v)); } catch { /* private mode */ } };

/**
 * Warns before the session ends and keeps it alive while the person is really working.
 *
 * The server signs a session out after SESSION_IDLE_SECONDS without any request. Typing a long form sends none, so without this the
 * screen could be signed out under someone who is busy. Real activity (keys, taps, mouse) therefore pings the server at most once a
 * minute. When nothing has happened for the idle limit minus the warning time, a dialog counts down and offers "Stay signed in".
 * The 12-hour cap on a sign-in cannot be extended, so for that one a banner just says how long is left.
 */
export function IdleGuard() {
  const { me, keepAlive, logout } = useAuth();
  const { t } = useI18n();
  const session = me?.session;
  const lastActivity = useRef(Date.now());
  const received = useRef(Date.now());
  const [idleLeft, setIdleLeft] = useState<number | null>(null);
  const [absLeft, setAbsLeft] = useState<number | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const ended = useRef(false);

  useEffect(() => { received.current = Date.now(); }, [session?.absolute_remaining]);

  const endSession = useCallback((idle: boolean) => {
    if (ended.current) return;
    ended.current = true;
    if (idle) { try { sessionStorage.setItem(IDLE_NOTICE_KEY, "1"); } catch { /* ignore */ } }
    void logout();
  }, [logout]);

  const stay = useCallback(() => {
    lastActivity.current = Date.now();
    writeShared(lastActivity.current);
    setIdleLeft(null);
    void keepAlive();
  }, [keepAlive]);

  useEffect(() => {
    if (!session) return undefined;
    ended.current = false;
    lastActivity.current = Date.now();
    writeShared(lastActivity.current);
    let lastWrite = 0;
    const onActivity = () => {
      const now = Date.now();
      // While the warning is up only the button counts: the server session is about to end whatever the mouse does.
      if (dialog.current?.open) return;
      lastActivity.current = now;
      if (now - lastWrite > 1000) { lastWrite = now; writeShared(now); }
      if (now - getLastApiAt() > PING_AFTER_MS) void keepAlive();
    };
    const events = ["keydown", "pointerdown", "pointermove", "scroll", "touchstart", "wheel"] as const;
    events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }));
    const tick = () => {
      const now = Date.now();
      const last = Math.max(lastActivity.current, readShared());
      // one minute of margin: the server may have heard about the latest activity up to a minute late
      const left = Math.ceil((last + session.idle_seconds * 1000 - 60_000 - now) / 1000);
      if (left <= 0) { endSession(true); return; }
      setIdleLeft(left <= session.warn_seconds ? left : null);
      const abs = Math.ceil(session.absolute_remaining - (now - received.current) / 1000);
      if (abs <= 0) { endSession(false); return; }
      setAbsLeft(abs <= ABSOLUTE_WARN_S ? abs : null);
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      events.forEach((e) => window.removeEventListener(e, onActivity));
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [session, keepAlive, endSession]);

  const showIdle = idleLeft !== null;
  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (showIdle && !el.open) el.showModal();
    if (!showIdle && el.open) el.close();
  }, [showIdle]);

  if (!session) return null;
  return (
    <>
      <dialog ref={dialog} className="stepup idle-dialog" aria-labelledby="idle-title" aria-describedby="idle-body"
              onCancel={(e) => { e.preventDefault(); stay(); }}>
        <h2 id="idle-title">{t("idle.title")}</h2>
        <p id="idle-body">{t("idle.body", { time: clock(Math.max(0, idleLeft ?? 0)) })}</p>
        <div className="row" style={{ gap: ".5rem", marginTop: ".75rem" }}>
          {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the one safe choice is the one to focus */}
          <button type="button" onClick={stay} autoFocus>{t("idle.stay")}</button>
          <button type="button" className="secondary" onClick={() => endSession(false)}>{t("common.signOut")}</button>
        </div>
      </dialog>
      {absLeft !== null && !showIdle && (
        <div className="idle-banner" role="status" aria-live="polite">
          {t("idle.absolute", { time: clock(absLeft) })}
        </div>
      )}
    </>
  );
}
