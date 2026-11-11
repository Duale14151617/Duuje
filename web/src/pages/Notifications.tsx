import { post, put } from "../api";
import { Status, useLoad, when } from "../hooks";

export default function Notifications() {
  const { data, error, reload } = useLoad<any[]>("/notifications");
  const prefs = useLoad<any>("/notifications/preferences");
  return (
    <>
      <h1>Notifications</h1>
      <div className="card">
        <b>Also send me notifications by</b>
        {prefs.data?.availableChannels.length === 0 && <p className="muted">No email or SMS provider is set up yet, so notifications appear here only.</p>}
        {prefs.data?.availableChannels.map((ch: string) => {
          const on = prefs.data.preferences.some((p: any) => p.channel === ch && p.enabled);
          return <label key={ch} style={{ display: "block" }}><input type="checkbox" checked={on} onChange={async (e) => { await put("/notifications/preferences", { channel: ch, enabled: e.target.checked }); prefs.reload(); }} /> {ch}</label>;
        })}
        <button className="ghost" onClick={async () => { await post("/notifications/read-all"); reload(); }}>Mark all read</button>
      </div>
      {error && <div className="error">{error}</div>}
      {data?.length === 0 && <p className="muted">Nothing yet.</p>}
      {data?.map((n) => (
        <div className="card" key={n.id}>
          <b>{n.title}</b> {!n.readAt && <Status value="New" />}
          <div>{n.body}</div>
          <div className="muted">{when(n.createdAt)}</div>
          {!n.readAt && <button className="ghost" onClick={async () => { await post(`/notifications/${n.id}/read`); reload(); }}>Mark read</button>}
        </div>
      ))}
    </>
  );
}
