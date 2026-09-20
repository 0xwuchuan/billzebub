import type { CSSProperties } from "react";

import { categoryColor } from "../../lib/labels";

export function CategoryPill({ name }: { name: string }) {
  return (
    <span
      className="cat-pill"
      style={{ "--cat-color": categoryColor(name) } as CSSProperties}
    >
      {name}
    </span>
  );
}
