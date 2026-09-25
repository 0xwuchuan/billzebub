import type { CSSProperties } from "react";

import { categoryColor } from "../../lib/labels";

export function CategoryChip({ name }: { name: string }) {
  const label = name.trim() === "" ? "Uncategorized" : name;
  const muted = label === "Uncategorized";
  const primary = label.split(",")[0]?.trim() ?? label;
  const color = muted ? "var(--bz-muted)" : categoryColor(primary);
  return (
    <span
      className={`cat-chip${muted ? " is-muted" : ""}`}
      style={{ "--cat-color": color } as CSSProperties}
    >
      <i className="cat-chip-dot" aria-hidden="true" />
      <span className="cat-chip-label">{label}</span>
    </span>
  );
}
