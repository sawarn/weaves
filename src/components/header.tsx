"use client";

import { ThemeToggle } from "@/components/theme-toggle";
import { NavPill } from "@/components/nav-pill";

export function Header() {
  return (
    <>
      <div className="fixed left-1/2 top-4 z-50 w-[min(36rem,calc(100vw-6.5rem))] -translate-x-1/2 sm:top-10 sm:w-auto">
        <NavPill />
      </div>
      <div className="fixed right-4 top-4 z-50 sm:right-6 sm:top-10">
        <ThemeToggle />
      </div>
    </>
  );
}

