import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Login as LoginRes, auth, post } from "../api";
import { Msg, useAction } from "../hooks";
import { AuthArt } from "../icons";

export function Login({ onDone }: { onDone: () => void }) {
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [f, setF] = useState({ email: "", password: "", displayName: "", phone: "", code: "" });
  const [role, setRole] = useState<"company" | "technician">("company");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const { run, error, busy, notice } = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    await run(async () => {
      if (mfaToken) {
        const r = await post<LoginRes>("/auth/mfa/verify", { mfaToken, code: f.code });
        auth.set(r.token!); nav("/"); onDone(); return;
      }
      if (mode === "register") { await post("/auth/register", { email: f.email, password: f.password, displayName: f.displayName }); }
      const r = await post<LoginRes>("/auth/login", { email: f.email, password: f.password });
      if (r.mfaRequired) { setMfaToken(r.mfaToken!); return; }
      auth.set(r.token!);
      if (mode === "register" && role === "technician") {
        // The account exists now. If the profile call fails, the Technician page offers the same form again.
        try { await post("/technicians/me", { displayName: f.displayName, phone: f.phone || undefined }); } catch { /* retried on /technician */ }
        nav("/technician"); onDone(); return;
      }
      nav("/"); onDone();
    });
  };

  return (
    <div className="auth">
    <AuthArt />
    <form className="card narrow" onSubmit={submit}>
      <h1>{mfaToken ? "Two-step check" : mode === "login" ? "Welcome back" : "Create your account"}</h1>
      {mfaToken ? (
        <>
          <p>Enter the 6-digit code from your authenticator app, or a recovery code.</p>
          <label>Code<input value={f.code} onChange={set("code")} autoComplete="one-time-code" autoFocus required /></label>
        </>
      ) : (
        <>
          {mode === "register" && (
            <div className="row" role="radiogroup" aria-label="Account type">
              <button type="button" className={role === "company" ? "primary" : "ghost"} onClick={() => setRole("company")}>I'm a company</button>
              <button type="button" className={role === "technician" ? "primary" : "ghost"} onClick={() => setRole("technician")}>I'm a technician</button>
            </div>
          )}
          {mode === "register" && <label>{role === "technician" ? "Full name" : "Name"}<input value={f.displayName} onChange={set("displayName")} required /></label>}
          {mode === "register" && role === "technician" && <label>Phone<input type="tel" value={f.phone} onChange={set("phone")} placeholder="+252 90 000 0000" required /></label>}
          <label>Email<input type="email" value={f.email} onChange={set("email")} autoComplete="username" required /></label>
          <label>Password<input type="password" value={f.password} onChange={set("password")} minLength={mode === "register" ? 12 : undefined} autoComplete={mode === "register" ? "new-password" : "current-password"} required /></label>
          {mode === "register" && <p className="muted">At least 12 characters.</p>}
        </>
      )}
      <Msg error={error} notice={notice} />
      <div className="row" style={{ marginTop: 12 }}>
        <button className="primary" disabled={busy}>{mfaToken ? "Verify" : mode === "login" ? "Sign in" : "Create account"}</button>
        {!mfaToken && <button type="button" className="ghost" onClick={() => setMode(mode === "login" ? "register" : "login")}>{mode === "login" ? "Register" : "Have an account?"}</button>}
      </div>
      {!mfaToken && <p><Link to="/recover">Forgot your password?</Link></p>}
    </form>
    </div>
  );
}

export function Recover() {
  const [step, setStep] = useState<"request" | "reset">("request");
  const [f, setF] = useState({ email: "", token: "", newPassword: "", code: "" });
  const { run, error, busy, notice } = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="card narrow">
      <h1>Account recovery</h1>
      {step === "request" ? (
        <form onSubmit={async (e) => { e.preventDefault(); if (await run(() => post("/auth/recovery/request", { email: f.email }), "If that account exists, a recovery token has been sent.")) setStep("reset"); }}>
          <label>Email<input type="email" value={f.email} onChange={set("email")} required /></label>
          <Msg error={error} notice={notice} />
          <button className="primary" disabled={busy}>Send recovery token</button>
        </form>
      ) : (
        <form onSubmit={async (e) => { e.preventDefault(); await run(() => post("/auth/recovery/reset", { token: f.token, newPassword: f.newPassword, code: f.code || undefined }), "Password changed. You can sign in now."); }}>
          <label>Recovery token<input value={f.token} onChange={set("token")} required /></label>
          <label>New password (12+ characters)<input type="password" minLength={12} value={f.newPassword} onChange={set("newPassword")} required /></label>
          <label>Authenticator or recovery code (only if you use two-factor)<input value={f.code} onChange={set("code")} /></label>
          <Msg error={error} notice={notice} />
          <button className="primary" disabled={busy}>Reset password</button>
        </form>
      )}
      <p><Link to="/login">Back to sign in</Link></p>
    </div>
  );
}
