import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type TopicProgress = Schemas["TopicProgress"];
export type DueCard = Schemas["DueCard"];
export type DailyPlan = Schemas["DailyPlanOut"];
export type MistakeGroup = Schemas["MistakeGroupOut"];
export type Profile = Schemas["ProfileOut"];

export const learningKeys = {
  progress: (moduleId: string) => ["progress", moduleId] as const,
  weakest: ["progress", "weakest"] as const,
  due: (moduleId?: string) => ["flashcards", "due", moduleId ?? "all"] as const,
  plan: ["daily-quiz", "plan"] as const,
  mistakes: (moduleId?: string) => ["mistakes", moduleId ?? "all"] as const,
  profile: ["profile"] as const,
};

export function useProgress(moduleId: string) {
  return useQuery({
    queryKey: learningKeys.progress(moduleId),
    queryFn: () => unwrap(api.GET("/api/v1/progress", { params: { query: { module_id: moduleId } } })),
  });
}

export function useWeakest() {
  return useQuery({
    queryKey: learningKeys.weakest,
    queryFn: () => unwrap(api.GET("/api/v1/progress/weakest", { params: { query: { limit: 5 } } })),
  });
}

export function useDueCards(moduleId?: string) {
  return useQuery({
    queryKey: learningKeys.due(moduleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/flashcards/due", { params: { query: moduleId ? { module_id: moduleId } : {} } })),
  });
}

export function useReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ cardId, rating, durationMs }: { cardId: string; rating: number; durationMs?: number }) =>
      unwrap(
        api.POST("/api/v1/flashcards/{card_id}/review", {
          params: { path: { card_id: cardId } },
          body: { rating, duration_ms: durationMs ?? null },
        }),
      ),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: ["progress"] }),
        qc.invalidateQueries({ queryKey: ["flashcards"] }),
      ]),
  });
}

export function useDailyPlan() {
  return useQuery({
    queryKey: learningKeys.plan,
    queryFn: () => unwrap(api.GET("/api/v1/daily-quiz/plan")),
  });
}

export function useStartDaily() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/daily-quiz", { body: {} })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["attempts"] }),
  });
}

export function useMistakes(moduleId?: string) {
  return useQuery({
    queryKey: learningKeys.mistakes(moduleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/mistakes", { params: { query: moduleId ? { module_id: moduleId } : {} } })),
  });
}

export function useProfile() {
  return useQuery({
    queryKey: learningKeys.profile,
    queryFn: () => unwrap(api.GET("/api/v1/profile")),
  });
}

/** "est. 72% · 14 attempts · last practised 6 days ago" (ARCHITECTURE.md §10). */
export function evidence(p: {
  strength: number;
  attempts: number;
  low_data: boolean;
  last_practised_at?: string | null;
}): string {
  const parts = [`est. ${Math.round(p.strength * 100)}%`, `${p.attempts} attempt${p.attempts === 1 ? "" : "s"}`];
  if (p.last_practised_at) {
    const days = Math.floor((Date.now() - new Date(p.last_practised_at).getTime()) / 86_400_000);
    parts.push(days <= 0 ? "practised today" : `last practised ${days} day${days === 1 ? "" : "s"} ago`);
  } else {
    parts.push("not practised yet");
  }
  if (p.low_data) parts.push("low data");
  return parts.join(" · ");
}

export function formatInterval(days: number): string {
  if (days < 1 / 24) return `${Math.max(1, Math.round(days * 1440))} min`;
  if (days < 1) return `${Math.round(days * 24)} h`;
  if (days < 30) return `${Math.round(days)} d`;
  if (days < 365) return `${Math.round(days / 30)} mo`;
  return `${(days / 365).toFixed(1)} y`;
}
