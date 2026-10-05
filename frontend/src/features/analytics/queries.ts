import { useQuery } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type MetricValue = Schemas["MetricOut"];
export type Overview = Schemas["OverviewOut"];
export type Trends = Schemas["TrendsOut"];
export type Week = Schemas["WeekOut"];
export type Readiness = Schemas["ReadinessOut"];
export type ModuleAnalytics = Schemas["ModuleAnalyticsOut"];
export type Summary = Schemas["SummaryOut"];

export const analyticsKeys = {
  dashboard: ["analytics", "dashboard"] as const,
  overview: ["analytics", "overview"] as const,
  trends: (moduleId?: string) => ["analytics", "trends", moduleId ?? "all"] as const,
  readiness: ["analytics", "readiness"] as const,
  module: (moduleId: string) => ["analytics", "module", moduleId] as const,
};

/** The order of Today's panels, most pressing first. */
export function useDashboardOrder() {
  return useQuery({
    queryKey: analyticsKeys.dashboard,
    queryFn: () => unwrap(api.GET("/api/v1/analytics/dashboard")),
  });
}

export function useOverview() {
  return useQuery({
    queryKey: analyticsKeys.overview,
    queryFn: () => unwrap(api.GET("/api/v1/analytics/overview")),
  });
}

export function useTrends(moduleId?: string) {
  return useQuery({
    queryKey: analyticsKeys.trends(moduleId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/trends", { params: { query: moduleId ? { module_id: moduleId } : {} } }),
      ),
  });
}

export function useReadiness() {
  return useQuery({
    queryKey: analyticsKeys.readiness,
    queryFn: () => unwrap(api.GET("/api/v1/analytics/readiness")),
  });
}

export function useModuleAnalytics(moduleId: string) {
  return useQuery({
    queryKey: analyticsKeys.module(moduleId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/modules/{module_id}", { params: { path: { module_id: moduleId } } }),
      ),
  });
}

export type Format = "percent" | "count" | "minutes" | "days";

export function formatValue(value: number | null | undefined, format: Format): string {
  if (value === null || value === undefined) return "–";
  switch (format) {
    case "percent":
      return `${Math.round(value * 100)}%`;
    case "minutes": {
      if (value < 60) return `${Math.round(value)} min`;
      const h = Math.floor(value / 60);
      const m = Math.round(value % 60);
      return m ? `${h} h ${m} min` : `${h} h`;
    }
    case "days":
      return `${value} day${value === 1 ? "" : "s"}`;
    default:
      return String(Math.round(value));
  }
}

/** "5 Oct" for a YYYY-MM-DD week start. */
export function shortDate(day: string): string {
  const [y = 1970, m = 1, d = 1] = day.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
