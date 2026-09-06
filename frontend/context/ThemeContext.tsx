"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

interface ThemeContextType {
  theme: Theme;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const STORAGE_KEY = "oxiverse_theme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("system");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("light");
  const [mounted, setMounted] = useState(false);

  const applyTheme = useCallback((targetTheme: Theme) => {
    if (typeof window === "undefined") return;

    const isDark =
      targetTheme === "dark" ||
      (targetTheme === "system" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);

    const root = document.documentElement;
    if (isDark) {
      root.classList.add("dark");
      root.classList.remove("light");
      root.style.colorScheme = "dark";
      setResolvedTheme("dark");
    } else {
      root.classList.remove("dark");
      root.classList.add("light");
      root.style.colorScheme = "light";
      setResolvedTheme("light");
    }
  }, []);

  useEffect(() => {
    setMounted(true);
    const stored = localStorage.getItem(STORAGE_KEY) as Theme | null;
    const initialTheme: Theme =
      stored === "light" || stored === "dark" || stored === "system"
        ? stored
        : "system";

    setThemeState(initialTheme);
    applyTheme(initialTheme);

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      const currentStored = localStorage.getItem(STORAGE_KEY) as Theme | null;
      if (!currentStored || currentStored === "system") {
        applyTheme("system");
      }
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [applyTheme]);

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
    try {
      localStorage.setItem(STORAGE_KEY, newTheme);
    } catch {
      // Ignore localStorage access errors
    }
    applyTheme(newTheme);
  };

  const toggleTheme = () => {
    const nextTheme = resolvedTheme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
  };

  return (
    <ThemeContext.Provider
      value={{
        theme,
        resolvedTheme: mounted ? resolvedTheme : "light",
        setTheme,
        toggleTheme,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
