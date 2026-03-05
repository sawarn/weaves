"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";

type ThemedLogoProps = {
  lightSrc: string;
  darkSrc: string;
  alt: string;
  className?: string;
  lightClassName?: string;
  darkClassName?: string;
  sizes?: string;
  priority?: boolean;
};

export function ThemedLogo({
  lightSrc,
  darkSrc,
  alt,
  className,
  lightClassName,
  darkClassName,
  sizes,
  priority,
}: ThemedLogoProps) {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const isDark = mounted && resolvedTheme === "dark";
  const src = isDark ? darkSrc : lightSrc;
  const themeClassName = isDark ? darkClassName : lightClassName;

  return (
    <Image
      src={src}
      alt={alt}
      fill
      sizes={sizes}
      priority={priority}
      className={[className, themeClassName].filter(Boolean).join(" ")}
    />
  );
}

