import { afterEach, describe, expect, it } from "vitest";

import {
  applyTheme,
  readStoredTheme,
  resolveTheme,
  syncThemeColor,
  systemTheme,
  THEME_CHROME_COLOR,
  THEME_STORAGE_KEY,
  writeStoredTheme,
} from "./theme";

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.colorScheme = "";
  document
    .querySelectorAll('meta[name="theme-color"]')
    .forEach((node) => node.remove());
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

  it("paints the theme-color meta with the elevated background", () => {
    const light = document.createElement("meta");
    light.name = "theme-color";
    light.media = "(prefers-color-scheme: light)";
    light.content = "#000000";
    const dark = document.createElement("meta");
    dark.name = "theme-color";
    dark.media = "(prefers-color-scheme: dark)";
    dark.content = "#ffffff";
    document.head.append(light, dark);

    syncThemeColor("light");
    expect(light.content).toBe(THEME_CHROME_COLOR.light);
    expect(dark.content).toBe(THEME_CHROME_COLOR.light);

    applyTheme("dark");
    expect(light.content).toBe(THEME_CHROME_COLOR.dark);
    expect(dark.content).toBe(THEME_CHROME_COLOR.dark);
    expect(THEME_CHROME_COLOR.dark).toBe("#1c1b1a");
    expect(THEME_CHROME_COLOR.light).toBe("#f2f0e5");
  });
});
