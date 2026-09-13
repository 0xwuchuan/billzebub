export const SEEN_STORAGE_KEY = "bz.quietRail.seen.v1";

export function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function takeEntrance(key: string): boolean {
  if (prefersReducedMotion()) {
    return false;
  }
  const seen = readSeen();
  if (seen[key] === true) {
    return false;
  }
  seen[key] = true;
  window.sessionStorage.setItem(SEEN_STORAGE_KEY, JSON.stringify(seen));
  return true;
}

function readSeen(): Record<string, boolean> {
  try {
    const raw = window.sessionStorage.getItem(SEEN_STORAGE_KEY);
    if (raw === null) {
      return {};
    }
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) {
      return {};
    }
    const next: Record<string, boolean> = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (value === true) {
        next[key] = true;
      }
    }
    return next;
  } catch {
    return {};
  }
}
