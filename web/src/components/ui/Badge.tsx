import type { ReactNode } from "react";

type Tone = "count" | "attention" | "blocking" | "confirmed" | "provisional";

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
