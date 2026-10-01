import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type Readiness = components["schemas"]["ReadinessResponse"];

export function useReadiness() {
  return useQuery({
    queryKey: ["system", "readiness"],
    queryFn: async (): Promise<Readiness> => {
      // 200 and 503 both carry a readiness body; anything else is a failure.
      const { data, error, response } = await api.GET("/api/v1/health/ready");
      const body = data ?? (response.status === 503 ? (error as Readiness) : undefined);
      if (!body) throw new Error(`Unexpected response ${response.status}`);
      return body;
    },
    refetchInterval: 15_000,
    retry: false,
  });
}
