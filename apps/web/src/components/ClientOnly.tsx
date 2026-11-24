"use client";

import { useSyncExternalStore } from "react";
import type { ReactNode } from "react";

const noop = () => () => {};

/** Render children only in the browser (the app reads localStorage / location.hash on first render). */
export function ClientOnly({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  const mounted = useSyncExternalStore(noop, () => true, () => false);
  return mounted ? children : fallback;
}
