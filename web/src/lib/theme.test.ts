import { afterEach, describe, expect, it } from "vitest";

import {
  applyTheme,
  readStoredTheme,
  resolveTheme,
  systemTheme,
  THEME_STORAGE_KEY,
  writeStoredTheme,
} from "./theme";

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.colorScheme = "";
});

describe("theme preference", () => {
  it("prefers a stored choice over the system scheme", () => {
    expect(resolveTheme("light", "dark")).toBe("light");
    expect(resolveTheme("dark", "light")).toBe("dark");
    expect(resolveTheme(null, "light")).toBe("light");
    expect(resolveTheme(null, "dark")).toBe("dark");
  });

  it("falls back to dark when the system scheme is unspecified", () => {
    expect(
      systemTheme(() => ({
        matches: false,
      })),
    ).toBe("dark");
  });

  it("reads and writes the persisted preference", () => {
    expect(readStoredTheme()).toBeNull();
    writeStoredTheme("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(readStoredTheme()).toBe("light");
  });

  it("applies the theme to the document root", () => {
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});
