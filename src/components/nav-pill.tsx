"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const nav = [
  { label: "Home", href: "/" },
  { label: "Our work", href: "/work" },
  { label: "About us", href: "/about" },
] as const;

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function NavPill() {
  const pathname = usePathname();

  return (
    <nav className="no-scrollbar flex max-w-full items-center gap-1 overflow-x-auto rounded-2xl border border-foreground/20 bg-background/75 p-1.5 text-xs backdrop-blur sm:gap-2 sm:p-2 sm:text-sm">
      {nav.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={[
              "shrink-0 whitespace-nowrap rounded-xl px-3 py-1.5 transition sm:px-4 sm:py-2",
              active
                ? "bg-foreground text-background"
                : "text-foreground/80 hover:text-foreground hover:bg-foreground/10",
            ].join(" ")}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

