import { useEffect, useState } from "react";

/**
 * Dev-only example-data switch. Reads `?data=worst|empty|one|1000`.
 * Production builds replace `import.meta.env.DEV` with false and drop the branch.
 * This module never talks to the API and never writes ledger data.
 */

export const FIXTURE_MODES = ["worst", "empty", "one", "1000"] as const;

export type FixtureMode = (typeof FIXTURE_MODES)[number];

const EVENT = "billzebub-fixture";

export function isFixtureMode(value: string | null): value is FixtureMode {
  return (
    value === "worst" ||
    value === "empty" ||
    value === "one" ||
    value === "1000"
  );
}

export function readFixtureMode(
  search: string = typeof window === "undefined" ? "" : window.location.search,
): FixtureMode | null {
  if (!import.meta.env.DEV) {
    return null;
  }
  const value = new URLSearchParams(search).get("data");
  return isFixtureMode(value) ? value : null;
}

export function writeFixtureMode(mode: FixtureMode | null): void {
  if (!import.meta.env.DEV || typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  if (mode === null) {
    url.searchParams.delete("data");
  } else {
    url.searchParams.set("data", mode);
  }
  window.history.replaceState(null, "", url);
  window.dispatchEvent(new Event(EVENT));
}

export function useFixtureMode(): FixtureMode | null {
  const [mode, setMode] = useState<FixtureMode | null>(readFixtureMode);

  useEffect(() => subscribeFixtureMode(() => setMode(readFixtureMode())), []);

  return mode;
}

export function subscribeFixtureMode(onChange: () => void): () => void {
  if (!import.meta.env.DEV || typeof window === "undefined") {
    return () => {};
  }
  window.addEventListener(EVENT, onChange);
  window.addEventListener("popstate", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("popstate", onChange);
  };
}
