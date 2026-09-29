import { useLayoutEffect, useRef } from "react";

// Keep the document's scroll range when views/stages contract. Measure the
// natural inner content, never the reserved outer box (which would accumulate).
// A new run starts a fresh floor; no scrolling or focus compensation is used.
export function useContentFloor(runId: string | undefined) {
  const region = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const floor = useRef({ runId, height: 0 });
  useLayoutEffect(() => {
    const outer = region.current, inner = content.current;
    if (!outer || !inner) return;
    if (floor.current.runId !== runId) floor.current = { runId, height: 0 };
    const measure = () => {
      floor.current.height = Math.max(floor.current.height, inner.getBoundingClientRect().height);
      outer.style.minHeight = `${floor.current.height}px`;
    };
    measure();
    // Covers disclosure changes, wrapping, fonts and non-React content growth.
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(inner);
    return () => observer.disconnect();
  });
  return { region, content };
}
