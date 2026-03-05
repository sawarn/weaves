"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";

export function ThemeToggle() {
  const { setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);

  if (!mounted) return null;

  const isDark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      aria-label="Toggle theme"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="rounded-full border border-foreground/20 bg-background/70 px-2.5 py-1.5 text-[11px] font-medium text-foreground backdrop-blur transition hover:border-foreground/40 sm:px-3 sm:text-xs"
    >
      {isDark ? "Light" : "Dark"}
    </button>
  );
}

