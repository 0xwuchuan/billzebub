import { MoonIcon, SunIcon } from "./icons";
import type { Theme } from "../lib/theme";

export function ThemeToggle({
  theme,
  onToggle,
}: {
  theme: Theme;
  onToggle: () => void;
}) {
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      className="icon-btn"
      type="button"
      aria-label={`Switch to ${next} theme`}
      onClick={onToggle}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
