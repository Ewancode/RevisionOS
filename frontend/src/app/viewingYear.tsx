/**
 * Which academic year the user is looking at. Defaults to the year marked
 * current; switching it changes what the sidebar and dashboard show without
 * touching older years' data (SPEC §6).
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { useYears, type Year } from "@/features/structure/queries";

const STORAGE_KEY = "revision-os:viewing-year";

interface ViewingYear {
  years: Year[];
  year: Year | undefined;
  setYearId: (id: string) => void;
  isPending: boolean;
}

const Context = createContext<ViewingYear | null>(null);

function stored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function ViewingYearProvider({ children }: { children: ReactNode }) {
  const years = useYears();
  const [yearId, setYearId] = useState<string | null>(stored);

  useEffect(() => {
    try {
      if (yearId) localStorage.setItem(STORAGE_KEY, yearId);
    } catch {
      // Remembering the choice is a convenience only.
    }
  }, [yearId]);

  const list = years.data ?? [];
  const year = list.find((y) => y.id === yearId) ?? list.find((y) => y.is_current) ?? list[0];

  return (
    <Context.Provider value={{ years: list, year, setYearId, isPending: years.isPending }}>
      {children}
    </Context.Provider>
  );
}

export function useViewingYear(): ViewingYear {
  const value = useContext(Context);
  if (!value) throw new Error("useViewingYear must be used inside ViewingYearProvider");
  return value;
}
