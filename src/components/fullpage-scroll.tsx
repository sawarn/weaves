"use client";

import { useMemo, useRef, useState, useEffect } from "react";

type Props = {
  children: React.ReactNode;
  sectionCount: number;
};

export function FullpageScroll({ children }: Props) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const sectionRefs = useRef<Array<HTMLDivElement | null>>([]);
  const [opacities, setOpacities] = useState<number[]>([]);


  const childArray = useMemo(() => {
    if (!Array.isArray(children)) return [children];
    return children;
  }, [children]);

  // Fade based on each section's real position/height in the scroller.
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;

    const updateOpacities = () => {
      const viewportCenter = el.scrollTop + el.clientHeight / 2;

      const nextOpacities = childArray.map((_, index) => {
        const sectionEl = sectionRefs.current[index];
        if (!sectionEl) return 1;

        const sectionTop = sectionEl.offsetTop;
        const sectionHeight = sectionEl.offsetHeight || el.clientHeight;
        const sectionCenter = sectionTop + sectionHeight / 2;

        const distanceFromCenter = Math.abs(viewportCenter - sectionCenter);
        const fadeRange = Math.max(sectionHeight * 0.75, el.clientHeight * 0.75);
        const normalized = Math.min(distanceFromCenter / fadeRange, 1);

        // Keep non-active sections visible enough while still emphasizing focus.
        return 1 - normalized * 0.35;
      });

      setOpacities(nextOpacities);
    };

    updateOpacities();
    el.addEventListener("scroll", updateOpacities, { passive: true });
    window.addEventListener("resize", updateOpacities);
    return () => {
      el.removeEventListener("scroll", updateOpacities);
      window.removeEventListener("resize", updateOpacities);
    };
  }, [childArray]);

  return (
    <div
      ref={rootRef}
      className="h-screen w-full overflow-y-auto scroll-smooth"
    >
      {childArray.map((child, index) => (
        <div
          key={index}
          ref={(node) => {
            sectionRefs.current[index] = node;
          }}
          style={{
            opacity: opacities[index] ?? 1,
            transition: "opacity 0.6s ease-out",
          }}
        >
          {child}
        </div>
      ))}
    </div>
  );
}

