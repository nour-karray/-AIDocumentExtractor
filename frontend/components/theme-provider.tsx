"use client";

import {
  createContext,
  type PropsWithChildren,
  useContext,
  useEffect,
  useMemo,
  useState
} from "react";

import { readStoredValue, storageKeys, writeStoredValue } from "@/lib/storage";

type ThemeName = "dark" | "light" | "system";

type ThemeContextValue = {
  theme: ThemeName;
  resolvedTheme: "dark" | "light";
  setTheme: (theme: ThemeName) => void;
  toggleTheme: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: PropsWithChildren) {
  const [theme, setThemeState] = useState<ThemeName>("system");
  const [systemTheme, setSystemTheme] = useState<"dark" | "light">("light");

  useEffect(() => {
    const stored = readStoredValue(storageKeys.theme, "system");
    setThemeState(stored === "light" || stored === "dark" || stored === "system" ? stored : "system");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const applySystemTheme = () => {
      setSystemTheme(mediaQuery.matches ? "dark" : "light");
    };

    applySystemTheme();
    mediaQuery.addEventListener("change", applySystemTheme);
    return () => mediaQuery.removeEventListener("change", applySystemTheme);
  }, []);

  const resolvedTheme = useMemo(
    () => (theme === "system" ? systemTheme : theme),
    [systemTheme, theme]
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
    document.documentElement.dataset.theme = resolvedTheme;
    writeStoredValue(storageKeys.theme, theme);
  }, [resolvedTheme, theme]);

  return (
    <ThemeContext.Provider
      value={{
        theme,
        resolvedTheme,
        setTheme: setThemeState,
        toggleTheme: () =>
          setThemeState((value) => {
            const current = value === "system" ? systemTheme : value;
            return current === "dark" ? "light" : "dark";
          })
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside ThemeProvider");
  }
  return context;
}
