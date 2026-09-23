"use client";

import { useEffect, useEffectEvent } from "react";

/** Call `callback` every `delayMs` milliseconds; pass `null` to pause. */
export function useInterval(callback: () => void, delayMs: number | null): void {
  const tick = useEffectEvent(callback);

  useEffect(() => {
    if (delayMs === null) return;
    const id = window.setInterval(() => tick(), delayMs);
    return () => window.clearInterval(id);
  }, [delayMs]);
}
