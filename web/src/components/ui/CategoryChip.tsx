import type { CSSProperties, ReactNode } from "react";

import { PATH_MARK } from "../../lib/categoryTree";
import { categoryColor, categoryPrimary } from "../../lib/labels";

export function CategoryChip({
  name,
  parentName = null,
  archived = false,
  unsure = false,
  onRefine,
}: {
  name: string;
  parentName?: string | null | undefined;
  archived?: boolean | undefined;
  unsure?: boolean | undefined;
  onRefine?: (() => void) | undefined;
}) {
  const label = name.trim() === "" ? "Uncategorized" : name;
  const muted = archived || label === "Uncategorized";
  const hueName = parentName ?? categoryPrimary(label);
  const color = muted ? "var(--bz-muted)" : categoryColor(hueName);
  const title =
    parentName != null && parentName !== ""
      ? `${parentName}${PATH_MARK}${label}`
      : label;
  return (
    <span
      className={`cat-chip${muted ? " is-muted" : ""}${parentName ? " is-child" : ""}${archived ? " is-archived" : ""}`}
      style={{ "--cat-base": color, "--cat-color": color } as CSSProperties}
      title={archived ? `${title} archived` : title}
    >
      <i className="cat-chip-dot" aria-hidden="true" />
      {parentName != null && parentName !== "" ? (
        <>
          <span className="cat-chip-parent" dir="auto">
            {parentName}
          </span>
          <span className="cat-chip-sep" aria-hidden="true">
            ›
          </span>
        </>
      ) : null}
      <span className="cat-chip-label" dir="auto">
        {label}
      </span>
      {archived ? <span className="cat-chip-archived">archived</span> : null}
      {unsure ? (
        <RefineAffordance onRefine={onRefine}>+ sub</RefineAffordance>
      ) : null}
    </span>
  );
}

function RefineAffordance({
  onRefine,
  children,
}: {
  onRefine?: (() => void) | undefined;
  children: ReactNode;
}) {
  if (onRefine === undefined) {
    return <span className="cat-chip-sub">{children}</span>;
  }
  return (
    <button
      className="cat-chip-sub"
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onRefine();
      }}
    >
      {children}
    </button>
  );
}
