export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "bz.theme";

export function isTheme(value: string | null): value is Theme {
  return value === "light" || value === "dark";
}

export function readStoredTheme(
  storage: Pick<Storage, "getItem"> | null = defaultStorage(),
): Theme | null {
  if (storage === null) {
    return null;
  }
  try {
    const raw = storage.getItem(THEME_STORAGE_KEY);
    return isTheme(raw) ? raw : null;
  } catch {
    return null;
  }
}

export function writeStoredTheme(
  theme: Theme,
  storage: Pick<Storage, "setItem"> | null = defaultStorage(),
): void {
  if (storage === null) {
    return;
  }
  try {
    storage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    return;
  }
}

export function systemTheme(
  matchMedia:
    | ((query: string) => MediaQueryList | { matches: boolean })
    | null = defaultMatchMedia(),
): Theme {
  if (matchMedia === null) {
    return "dark";
  }
  if (matchMedia("(prefers-color-scheme: light)").matches) {
    return "light";
  }
  if (matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "dark";
}

export function resolveTheme(stored: Theme | null, system: Theme): Theme {
  return stored ?? system;
}

export function applyTheme(
  theme: Theme,
  root: HTMLElement | null = defaultRoot(),
): void {
  if (root === null) {
    return;
  }
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}

function defaultStorage(): Pick<Storage, "getItem" | "setItem"> | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function defaultMatchMedia():
  ((query: string) => MediaQueryList | { matches: boolean }) | null {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return null;
  }
  return (query: string) => window.matchMedia(query);
}

function defaultRoot(): HTMLElement | null {
  if (typeof document === "undefined") {
    return null;
  }
  return document.documentElement;
}
