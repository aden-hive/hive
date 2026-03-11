import { useTheme } from "./ThemeProvider";

export default function ThemeToggle() {

  const { theme, setTheme } = useTheme();

  return (
    <button
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="px-3 py-1 text-xs border rounded-md"
    >
      {theme === "dark" ? "☀" : "🌙"}
    </button>
  );
}