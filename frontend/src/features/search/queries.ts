import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type SearchResult = Schemas["SearchOut"];
export type Passage = Schemas["PassageOut"];

/** The value, once it has stopped changing for `ms`. */
export function useDebounced<T>(value: T, ms = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

export function useSearch(q: string, moduleId?: string) {
  const query = q.trim();
  return useQuery({
    queryKey: ["search", query, moduleId ?? null],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/search", { params: { query: { q: query, module_id: moduleId } } }),
      ),
    enabled: query.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}
