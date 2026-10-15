import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Branch, Page, Rank } from "../api/types";
import { useFetch } from "../api/useFetch";
import { useAuth } from "../auth/AuthContext";
import { Chip, ErrorNotice, Field, Loading, Notice } from "../components/ui";
import { useI18n, type Key } from "../i18n";

function RankEditor({ rank, onDone }: { rank: Rank; onDone: () => void }) {
  const { t } = useI18n();
  const [nameEn, setNameEn] = useState(rank.name_en);
  const [nameSo, setNameSo] = useState(rank.name_so);
  const [error, setError] = useState<unknown>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/ranks/${rank.id}/`, { method: "PATCH", body: { name_en: nameEn, name_so: nameSo, version: rank.version } });
      onDone();
    } catch (err) { setError(err); }
  }
  return (
    <form onSubmit={(e) => void save(e)} style={{ marginTop: ".5rem" }}>
      <ErrorNotice error={error} />
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
            {["enlisted", "warrant", "officer", "unspecified"].map((c) => <option key={c} value={c}>{t(`cat.${c}` as Key)}</option>)}
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
        {ranks.data?.results.map((r) => (
          <li key={r.id} className="item">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <h2>{r.code} {name(r)}</h2>
                <span className="muted">
                  {branchName(r.branch)} · {t(`cat.${r.category}` as Key)}
                  {!r.name_so && <> · {t("ranks.translationPending")}</>}
                </span>
              </div>
              <Chip tone={r.approval_status}>{t(`status.${r.approval_status}` as Key)}</Chip>
            </div>
            {(canEdit || canApprove) && editing !== r.id && (
              <div className="row" style={{ marginTop: ".5rem" }}>
                {canEdit && <button className="secondary" onClick={() => setEditing(r.id)}>{t("common.edit")}</button>}
                {canApprove && r.approval_status === "draft" && <button onClick={() => void act(r, "approve")}>{t("ranks.approve")}</button>}
                {canApprove && r.approval_status === "approved" && <button className="secondary" onClick={() => void act(r, "unapprove")}>{t("ranks.unapprove")}</button>}
              </div>
            )}
            {editing === r.id && <RankEditor rank={r} onDone={() => { setEditing(null); ranks.reload(); }} />}
          </li>
        ))}
      </ul>
    </>
  );
}
