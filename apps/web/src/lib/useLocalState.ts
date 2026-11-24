"use client";

import { useEffect, useState } from "react";

/** useState persisted to localStorage. Only use inside <ClientOnly> (reads storage on first render). */
export function useLocalState<T extends object>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw) return { ...initial, ...(JSON.parse(raw) as Partial<T>) };
    } catch {
      /* storage unavailable (private mode) */
    }
    return initial;
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* ignore */
    }
  }, [key, value]);
  return [value, setValue];
}
