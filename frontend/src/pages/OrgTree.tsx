import { useState } from "react";
import type { TreeNode } from "../api/types";
import { useFetch } from "../api/useFetch";
import { ErrorNotice, Chip, Field, Loading } from "../components/ui";
import { useI18n } from "../i18n";

function Node({ node, depth }: { node: TreeNode; depth: number }) {
  const { t, name } = useI18n();
  const [open, setOpen] = useState(depth < 2);
  const hasKids = node.children.length > 0;
  return (
    <li>
      <div className="row treerow" style={{ paddingLeft: `${depth * 1.1}rem` }}>
        {hasKids
          ? <button className="secondary tog" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "−" : "+"}</button>
          : <span className="tog-gap" />}
        <span>{name(node)}</span>
        <span className="muted">{node.code}</span>
        {!node.active && <Chip tone="draft">{t("tree.inactive")}</Chip>}
      </div>
      {hasKids && open && <ul className="list">{node.children.map((c) => <Node key={c.id} node={c} depth={depth + 1} />)}</ul>}
    </li>
  );
}

export function OrgTree() {
  const { t } = useI18n();
  const [inactive, setInactive] = useState(false);
  const tree = useFetch<{ count: number; truncated: boolean; roots: TreeNode[] }>("/organization/units/tree/", { include_inactive: inactive ? 1 : undefined });
  return (
    <>
      <h1>{t("tree.title")}</h1>
      <Field label={t("tree.showInactive")}>
        <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
      </Field>
      <ErrorNotice error={tree.error} />
      {tree.loading && !tree.data ? <Loading /> : null}
      {tree.data && tree.data.roots.length === 0 && <p>{t("tree.empty")}</p>}
      {tree.data?.truncated && <p className="muted">{t("tree.truncated", { n: tree.data.count })}</p>}
      <ul className="list">{tree.data?.roots.map((n) => <Node key={n.id} node={n} depth={0} />)}</ul>
    </>
  );
}
