import { useCallback, useState } from "react";

import {
  applyTheme,
  readStoredTheme,
  resolveTheme,
  systemTheme,
  writeStoredTheme,
  type Theme,
} from "../lib/theme";

export function useTheme(): {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
} {
  const [theme, setThemeState] = useState<Theme>(() => {
    const resolved = resolveTheme(readStoredTheme(), systemTheme());
    applyTheme(resolved);
    return resolved;
  });

  const setTheme = useCallback((next: Theme) => {
    writeStoredTheme(next);
    applyTheme(next);
    setThemeState(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [setTheme, theme]);

  return { theme, setTheme, toggleTheme };
}
