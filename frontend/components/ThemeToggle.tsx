"use client";

import { useTheme } from "@/context/ThemeContext";
import { Sun, Moon, Monitor } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface ThemeToggleProps {
  className?: string;
  showLabel?: boolean;
}

export function ThemeToggle({ className, showLabel = false }: ThemeToggleProps) {
  const { resolvedTheme, toggleTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div
        className={cn(
          "w-9 h-9 rounded-lg flex items-center justify-center text-on-surface-variant opacity-70",
          className
        )}
      >
        <span className="w-5 h-5 block" />
      </div>
    );
  }

  const isDark = resolvedTheme === "dark";

  return (
    <button
      onClick={toggleTheme}
      type="button"
      className={cn(
        "relative rounded-lg flex items-center gap-2 p-2 text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        !showLabel && "w-9 h-9 justify-center",
        className
      )}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
    >
      {isDark ? (
        <Sun
          className="w-5 h-5 text-amber-400 transition-transform duration-300 rotate-0 hover:rotate-45 shrink-0"
          strokeWidth={1.5}
        />
      ) : (
        <Moon
          className="w-5 h-5 text-on-surface-variant transition-transform duration-300 rotate-0 hover:-rotate-12 shrink-0"
          strokeWidth={1.5}
        />
      )}
      {showLabel && (
        <span className="font-caption text-caption">
          {isDark ? "Light Mode" : "Dark Mode"}
        </span>
      )}
    </button>
  );
}

export function ThemeSelector({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const options = [
    { value: "light" as const, label: "Light", icon: Sun },
    { value: "dark" as const, label: "Dark", icon: Moon },
    { value: "system" as const, label: "System", icon: Monitor },
  ];

  if (!mounted) {
    return <div className={cn("h-11 bg-surface-container rounded-lg animate-pulse", className)} />;
  }

  return (
    <div
      className={cn(
        "inline-flex p-1 bg-surface-container rounded-lg border border-outline-variant/40 gap-1",
        className
      )}
    >
      {options.map((opt) => {
        const Icon = opt.icon;
        const active = theme === opt.value;
        return (
          <button
            key={opt.value}
            onClick={() => setTheme(opt.value)}
            type="button"
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded-md font-label-sm text-label-sm transition-all",
              active
                ? "bg-surface-container-lowest text-primary font-semibold shadow-sm border border-outline-variant/30"
                : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high/50"
            )}
            aria-pressed={active}
          >
            <Icon className="w-4 h-4 shrink-0" strokeWidth={1.5} />
            <span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
