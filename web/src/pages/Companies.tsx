import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { post } from "../api";
import { Msg, Status, useAction, useLoad, useMe } from "../hooks";
import { EmptyArt, HeroArt, Icon } from "../icons";

const greeting = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };
const initials = (s: string) => s.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";

function Kpi({ label, value, tone, to, icon }: { label: string; value: number | string; tone: string; to?: string; icon: string }) {
  const inner = (<><span className="kpi-icon"><Icon name={icon} size={18} /></span><span className="kpi-label">{label}</span><span className="kpi-value">{value}</span></>);
  return to ? <Link to={to} className={`kpi ${tone}`}>{inner}</Link> : <div className={`kpi ${tone}`}>{inner}</div>;
}

export default function Companies() {
  const { me, reload } = useMe();
  const [showForm, setShowForm] = useState(me.companies.length === 0);
  const [f, setF] = useState({ displayName: "", businessCategory: "", contactEmail: "", contactPhone: "", registrationRef: "" });
  const a = useAction();
  const notes = useLoad<any[]>("/notifications");
  const queue = useLoad<any[]>(me.platform.companyVerify ? "/platform/companies?status=Pending" : null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const create = async (e: FormEvent) => { e.preventDefault(); if (await a.run(() => post("/companies", f), "Submitted for review.")) { reload(); setShowForm(false); } };

  const approved = me.companies.filter((c) => c.verification === "Approved").length;
  const pending = me.companies.length - approved;
  const unread = notes.data ? notes.data.filter((n) => !n.readAt).length : 0;
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const first = me.displayName.split(" ")[0];

  return (
    <>
      <section className="hero">
        <div className="hero-art"><HeroArt /></div>
        <small>{today}</small>
        <h1>{greeting()}, {first}</h1>
        <p>{me.companies.length === 0 ? "Register your company to start receiving and managing jobs." : pending > 0 ? `${pending} of your companies ${pending === 1 ? "is" : "are"} waiting for verification.` : "Everything is verified. Open a company to manage jobs, staff and finance."}</p>
        <div className="hero-actions"><button className="primary" onClick={() => setShowForm(!showForm)}>{showForm ? <><Icon name="x" size={16} /> Close form</> : <><Icon name="plus" size={16} /> Register a company</>}</button></div>
      </section>

      <div className="kpis">
        <Kpi label="Companies" value={me.companies.length} tone="" icon="building" />
        <Kpi label="Verified" value={approved} tone="green" icon="check" />
        <Kpi label="Pending review" value={pending} tone="amber" icon="clock" />
        <Kpi label="Unread alerts" value={unread} tone="orange" to="/notifications" icon="bell" />
        {me.platform.companyVerify && <Kpi label="Awaiting your review" value={queue.data ? queue.data.length : "–"} tone="orange" to="/admin/companies" icon="shield" />}
      </div>

      {showForm && (
        <form className="card" onSubmit={create}>
          <h2 style={{ marginTop: 0 }}>Register a company</h2>
          <div className="row">
            <label>Name<input value={f.displayName} onChange={set("displayName")} placeholder="e.g. Garowe Builders Ltd" required /></label>
            <label>Business category<input value={f.businessCategory} onChange={set("businessCategory")} placeholder="e.g. Construction and maintenance" required /></label>
            <label>Contact email<input type="email" value={f.contactEmail} onChange={set("contactEmail")} required /></label>
            <label>Phone<input type="tel" value={f.contactPhone} onChange={set("contactPhone")} placeholder="+252 90 000 0000" /></label>
            <label>Registration reference<input value={f.registrationRef} onChange={set("registrationRef")} /></label>
          </div>
          <Msg error={a.error} notice={a.notice} />
          <button className="primary" disabled={a.busy}>Submit for verification</button>
        </form>
      )}

      <div className="section-head"><h2>Your companies</h2></div>
      {me.companies.length === 0 ? (
        <div className="empty"><EmptyArt /><div>You are not part of a company yet.</div></div>
      ) : (
        <div className="cgrid">
          {me.companies.map((c) => (
            <Link className="ccard" key={c.id} to={`/companies/${c.id}`}>
              <span className="avatar">{initials(c.displayName)}</span>
              <span className="cinfo">
                <b>{c.displayName}</b>
                <span className="roles">{c.roles.map((r) => <i key={r}>{r.replace(/_/g, " ")}</i>)}</span>
              </span>
              <Status value={c.verification} />
            </Link>
          ))}
        </div>
      )}
      {!showForm && a.notice && <Msg notice={a.notice} />}
    </>
  );
}
