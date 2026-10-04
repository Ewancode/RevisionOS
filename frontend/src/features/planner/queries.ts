import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type Exam = Schemas["ExamOut"];
export type ExamIn = Schemas["ExamIn"];
export type ExamUpdate = Schemas["ExamUpdate"];
export type Availability = Schemas["AvailabilityOut"];
export type AvailabilityIn = Schemas["AvailabilityIn"];
export type Proposal = Schemas["AvailabilityProposal"];
export type Preferences = Schemas["PreferencesOut"];
export type PreferencesIn = Schemas["PreferencesIn"];
export type Plan = Schemas["PlanOut"];
export type StudySession = Schemas["StudySessionOut"];
export type CalendarDay = Schemas["CalendarDay"];
export type BuiltSession = Schemas["BuiltSession"];
export type BuiltBlock = Schemas["BuiltBlock"];
export type Notification = Schemas["NotificationOut"];

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export const plannerKeys = {
  exams: (moduleId?: string) => ["exams", moduleId ?? "all"] as const,
  availability: ["availability"] as const,
  preferences: ["planner", "preferences"] as const,
  plan: ["plan"] as const,
  calendar: (start: string, end: string) => ["calendar", start, end] as const,
  builder: (minutes: number) => ["session-builder", minutes] as const,
  recommendations: ["recommendations"] as const,
  notifications: ["notifications"] as const,
};

/** Anything that changes the plan: refetch everything planned from it. */
function usePlanChanged() {
  const qc = useQueryClient();
  return () =>
    Promise.all(
      ["exams", "plan", "calendar", "session-builder", "recommendations", "notifications", "daily-quiz", "flashcards"].map((k) =>
        qc.invalidateQueries({ queryKey: [k] }),
      ),
    );
}

// --- exams ---------------------------------------------------------------------------------

export function useExams(moduleId?: string) {
  return useQuery({
    queryKey: plannerKeys.exams(moduleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/exams", { params: { query: moduleId ? { module_id: moduleId } : {} } })),
  });
}

export function useExamMutations() {
  const changed = usePlanChanged();
  return {
    create: useMutation({
      mutationFn: (body: ExamIn) => unwrap(api.POST("/api/v1/exams", { body })),
      onSuccess: changed,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: ExamUpdate }) =>
        unwrap(api.PATCH("/api/v1/exams/{exam_id}", { params: { path: { exam_id: id } }, body })),
      onSuccess: changed,
    }),
    remove: useMutation({
      mutationFn: (id: string) =>
        unwrap(api.DELETE("/api/v1/exams/{exam_id}", { params: { path: { exam_id: id } } })),
      onSuccess: changed,
    }),
  };
}

// --- availability and preferences --------------------------------------------------------------

export function useAvailability() {
  return useQuery({
    queryKey: plannerKeys.availability,
    queryFn: () => unwrap(api.GET("/api/v1/availability")),
  });
}

export function useSetAvailability() {
  const qc = useQueryClient();
  const changed = usePlanChanged();
  return useMutation({
    mutationFn: (body: AvailabilityIn) => unwrap(api.PUT("/api/v1/availability", { body })),
    onSuccess: (data) => {
      qc.setQueryData(plannerKeys.availability, data);
      return changed();
    },
  });
}

export function useDeleteOverride() {
  const qc = useQueryClient();
  const changed = usePlanChanged();
  return useMutation({
    mutationFn: (day: string) =>
      unwrap(api.DELETE("/api/v1/availability/overrides/{day}", { params: { path: { day } } })),
    onSuccess: (data) => {
      qc.setQueryData(plannerKeys.availability, data);
      return changed();
    },
  });
}

export function useParseAvailability() {
  return useMutation({
    mutationFn: (text: string) => unwrap(api.POST("/api/v1/availability/parse", { body: { text } })),
  });
}

export function usePreferences() {
  return useQuery({
    queryKey: plannerKeys.preferences,
    queryFn: () => unwrap(api.GET("/api/v1/planner/preferences")),
  });
}

export function useSetPreferences() {
  const qc = useQueryClient();
  const changed = usePlanChanged();
  return useMutation({
    mutationFn: (body: PreferencesIn) => unwrap(api.PATCH("/api/v1/planner/preferences", { body })),
    onSuccess: (data) => {
      qc.setQueryData(plannerKeys.preferences, data);
      return changed();
    },
  });
}

// --- the plan and the calendar -----------------------------------------------------------------

export function usePlan() {
  return useQuery({ queryKey: plannerKeys.plan, queryFn: () => unwrap(api.GET("/api/v1/plan")) });
}

export function useCalendar(start: string, end: string) {
  return useQuery({
    queryKey: plannerKeys.calendar(start, end),
    queryFn: () => unwrap(api.GET("/api/v1/calendar", { params: { query: { start, end } } })),
  });
}

export function useSessionActions() {
  const changed = usePlanChanged();
  return {
    move: useMutation({
      mutationFn: ({ id, day, minutes }: { id: string; day: string; minutes?: number }) =>
        unwrap(
          api.PATCH("/api/v1/sessions/{session_id}", {
            params: { path: { session_id: id } },
            body: { day, minutes: minutes ?? null },
          }),
        ),
      onSuccess: changed,
    }),
    status: useMutation({
      mutationFn: ({ id, status }: { id: string; status: StudySession["status"] }) =>
        unwrap(
          api.POST("/api/v1/sessions/{session_id}/status", {
            params: { path: { session_id: id } },
            body: { status },
          }),
        ),
      onSuccess: changed,
    }),
  };
}

/** "I have N minutes": built on demand, so not cached for long. */
export function useBuiltSession(minutes: number | null) {
  return useQuery({
    queryKey: plannerKeys.builder(minutes ?? 0),
    queryFn: () => unwrap(api.GET("/api/v1/session-builder", { params: { query: { minutes: minutes ?? 0 } } })),
    enabled: minutes !== null,
    staleTime: 30_000,
  });
}

/** What to study next, best first, with the measurements behind each. */
export function useRecommendations() {
  return useQuery({
    queryKey: plannerKeys.recommendations,
    queryFn: () => unwrap(api.GET("/api/v1/recommendations", { params: { query: { limit: 3 } } })),
  });
}

// --- notifications -------------------------------------------------------------------------------

export function useNotifications() {
  return useQuery({
    queryKey: plannerKeys.notifications,
    queryFn: () => unwrap(api.GET("/api/v1/notifications")),
    refetchInterval: 5 * 60_000,
  });
}

export function useNotificationActions() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: plannerKeys.notifications });
  return {
    read: useMutation({
      mutationFn: (id: number) =>
        unwrap(
          api.POST("/api/v1/notifications/{notification_id}/read", {
            params: { path: { notification_id: id } },
          }),
        ),
      onSuccess: refresh,
    }),
    readAll: useMutation({
      mutationFn: () => unwrap(api.POST("/api/v1/notifications/read-all")),
      onSuccess: refresh,
    }),
  };
}

// --- dates ----------------------------------------------------------------------------------------

/** A local calendar date as YYYY-MM-DD (never via UTC, which can shift the day). */
export function isoDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function parseDay(day: string): Date {
  const [y = 1970, m = 1, d = 1] = day.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(day: string, n: number): string {
  const d = parseDay(day);
  d.setDate(d.getDate() + n);
  return isoDay(d);
}

/** Monday of the week containing the day. */
export function weekStart(day: string): string {
  return addDays(day, -((parseDay(day).getDay() + 6) % 7));
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function inDays(days: number): string {
  if (days <= 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}
