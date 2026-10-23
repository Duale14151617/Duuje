import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Branch, Page, Rank } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, Loading, Notice } from "../components/ui";
import { useI18n, type Key } from "../i18n";

const CATEGORIES = ["enlisted", "warrant", "officer", "unspecified", "general_officer", "senior_officer", "junior_officer", "inspector", "nco", "askari"];

function RankEditor({ rank, onDone }: { rank: Rank; onDone: () => void }) {
  const { t } = useI18n();
  const [nameEn, setNameEn] = useState(rank.name_en);
  const [nameSo, setNameSo] = useState(rank.name_so);
  const [code, setCode] = useState(rank.code);
  const [category, setCategory] = useState<string>(rank.category);
  const [error, setError] = useState<unknown>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/ranks/${rank.id}/`, { method: "PATCH", body: { code, category, name_en: nameEn, name_so: nameSo, version: rank.version } });
      onDone();
    } catch (err) { setError(err); }
  }
  return (
    <form onSubmit={(e) => void save(e)} style={{ marginTop: ".5rem" }}>
      <ErrorNotice error={error} />
      <Field label={t("ranks.code")}><input value={code} onChange={(e) => setCode(e.target.value)} required maxLength={16} /></Field>
      <Field label={t("ranks.category")}>
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{t(`cat.${c}` as Key)}</option>)}
        </select>
      </Field>
      <Field label={t("ranks.nameEn")}><input value={nameEn} onChange={(e) => setNameEn(e.target.value)} required /></Field>
      <Field label={t("ranks.nameSo")}><input value={nameSo} onChange={(e) => setNameSo(e.target.value)} /></Field>
      <div className="row">
        <button type="submit">{t("common.save")}</button>
        <button type="button" className="secondary" onClick={onDone}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}

export function Ranks() {
  const { t, name } = useI18n();
  const { can } = useAuth();
  const [branch, setBranch] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [swapping, setSwapping] = useState<string | null>(null);
  const [swapWith, setSwapWith] = useState("");
  const [actionError, setActionError] = useState<unknown>(null);
  const ranks = useFetch<Page<Rank>>("/ranks/", { branch, category, approval_status: status, page_size: 100 });
  const branches = useFetch<Page<Branch>>("/organization/branches/", { page_size: 100 });
  const canEdit = can("ranks.manage");
  const canApprove = can("ranks.approve");
  const branchName = (id: string) => {
    const b = branches.data?.results.find((x) => x.id === id);
    return b ? name(b) : "";
  };

  async function act(rank: Rank, verb: "approve" | "unapprove") {
    setActionError(null);
    try {
      await api(`/ranks/${rank.id}/${verb}/`, { method: "POST" });
      ranks.reload();
    } catch (err) { setActionError(err); }
  }

  // Swap positions with the neighbour above (more senior) or below (more junior). Only offered when no filter hides ranks, so the
  // neighbour really is the next rank in the order.
  const unfiltered = !category && !status;
  const active = (ranks.data?.results ?? []).filter((x) => x.active);
  async function move(rank: Rank, dir: "up" | "down") {
    const same = active.filter((x) => x.branch === rank.branch).sort((a, b) => a.sort_order - b.sort_order);
    const i = same.findIndex((x) => x.id === rank.id);
    const other = same[dir === "up" ? i + 1 : i - 1];
    if (!other) return;
    setActionError(null);
    try {
      await api("/ranks/swap/", { method: "POST", body: { first: rank.id, second: other.id } });
      ranks.reload();
    } catch (err) { setActionError(err); }
  }

  // Swap with ANY other active rank of the same branch (not only the neighbour).
  async function swapRanks(rank: Rank) {
    if (!swapWith) return;
    setActionError(null);
    try {
      await api("/ranks/swap/", { method: "POST", body: { first: rank.id, second: swapWith } });
      setSwapping(null);
      setSwapWith("");
      ranks.reload();
    } catch (err) { setActionError(err); }
  }

  // Most senior first, so "Move up" really moves the row up the screen. Retired ranks go last.
  const shown = [...(ranks.data?.results ?? [])].sort((a, b) =>
    (a.branch === b.branch ? 0 : a.branch < b.branch ? -1 : 1) || Number(b.active) - Number(a.active) || b.sort_order - a.sort_order);

  return (
    <>
      <h1>{t("ranks.title")}</h1>
      <Notice>{t("ranks.draftNotice")}</Notice>
      <div className="grid" style={{ marginBottom: "1rem" }}>
        <Field label={t("ranks.branch")}>
          <select value={branch} onChange={(e) => setBranch(e.target.value)}>
            <option value="">{t("common.all")}</option>
            {branches.data?.results.map((b) => <option key={b.id} value={b.id}>{name(b)}</option>)}
          </select>
        </Field>
        <Field label={t("ranks.category")}>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">{t("common.all")}</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{t(`cat.${c}` as Key)}</option>)}
          </select>
        </Field>
        <Field label={t("ranks.status")}>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("common.all")}</option>
            <option value="draft">{t("status.draft")}</option>
            <option value="approved">{t("status.approved")}</option>
          </select>
        </Field>
      </div>
      <ErrorNotice error={ranks.error ?? actionError} />
      {ranks.loading && !ranks.data ? <Loading /> : null}
      {ranks.data && ranks.data.results.length === 0 && <p>{t("common.empty")}</p>}
      <ul className="list">
        {shown.map((r) => (
          <li key={r.id} className="item">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <h2>{r.code} {name(r)}</h2>
                <span className="muted">
                  {branchName(r.branch)} · {t(`cat.${r.category}` as Key)} · {t("ranks.position")} {r.sort_order}
                  {!r.name_so && <> · {t("ranks.translationPending")}</>}
                </span>
              </div>
              <Chip tone={r.approval_status}>{t(`status.${r.approval_status}` as Key)}</Chip>
            </div>
            {(canEdit || canApprove) && editing !== r.id && (
              <div className="row" style={{ marginTop: ".5rem" }}>
                {canEdit && <button className="secondary" onClick={() => setEditing(r.id)}>{t("common.edit")}</button>}
                {canEdit && unfiltered && r.active && <button className="secondary" onClick={() => void move(r, "up")}>{t("ranks.moveUp")}</button>}
                {canEdit && unfiltered && r.active && <button className="secondary" onClick={() => void move(r, "down")}>{t("ranks.moveDown")}</button>}
                {canEdit && unfiltered && r.active && <button className="secondary" onClick={() => { setSwapping(r.id); setSwapWith(""); }}>{t("ranks.swapWith")}</button>}
                {canApprove && r.approval_status === "draft" && <button onClick={() => void act(r, "approve")}>{t("ranks.approve")}</button>}
                {canApprove && r.approval_status === "approved" && <button className="secondary" onClick={() => void act(r, "unapprove")}>{t("ranks.unapprove")}</button>}
              </div>
            )}
            {swapping === r.id && (
              <div className="row" style={{ marginTop: ".5rem" }}>
                <select value={swapWith} onChange={(e) => setSwapWith(e.target.value)} aria-label={t("ranks.swapWith")}>
                  <option value="">{t("ranks.swapChoose")}</option>
                  {active.filter((x) => x.branch === r.branch && x.id !== r.id).sort((a, b) => b.sort_order - a.sort_order)
                    .map((x) => <option key={x.id} value={x.id}>{x.code} {name(x)}</option>)}
                </select>
                <button type="button" disabled={!swapWith} onClick={() => void swapRanks(r)}>{t("ranks.swapDo")}</button>
                <button type="button" className="secondary" onClick={() => setSwapping(null)}>{t("common.cancel")}</button>
              </div>
            )}
            {editing === r.id && <RankEditor rank={r} onDone={() => { setEditing(null); ranks.reload(); }} />}
          </li>
        ))}
      </ul>
    </>
  );
}
