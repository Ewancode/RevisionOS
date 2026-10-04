import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type CodingConfig = Schemas["CodingConfigOut"];
export type Exercise = Schemas["ExerciseOut"];
export type ExerciseSummary = Schemas["ExerciseSummary"];
export type ExerciseIn = Schemas["ExerciseIn"];
export type Submission = Schemas["SubmissionOut"];
export type Hints = Schemas["HintsOut"];

export const codingKeys = {
  config: ["coding", "config"] as const,
  exercises: (moduleId: string) => ["coding", "exercises", moduleId] as const,
  exercise: (id: string) => ["coding", "exercise", id] as const,
  submissions: (id: string) => ["coding", "submissions", id] as const,
  hints: (id: string) => ["coding", "hints", id] as const,
  questionHints: (attemptId: string, questionId: string) => ["hints", attemptId, questionId] as const,
};

export function useCodingConfig() {
  return useQuery({
    queryKey: codingKeys.config,
    queryFn: () => unwrap(api.GET("/api/v1/coding/config")),
    staleTime: Infinity,
  });
}

export function useExercises(moduleId: string) {
  return useQuery({
    queryKey: codingKeys.exercises(moduleId),
    queryFn: () => unwrap(api.GET("/api/v1/coding/exercises", { params: { query: { module_id: moduleId } } })),
  });
}

export function useExercise(id: string) {
  return useQuery({
    queryKey: codingKeys.exercise(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/coding/exercises/{exercise_id}", { params: { path: { exercise_id: id } } })),
  });
}

export function useSubmissions(id: string) {
  return useQuery({
    queryKey: codingKeys.submissions(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/coding/exercises/{exercise_id}/submissions", { params: { path: { exercise_id: id } } }),
      ),
  });
}

export function useExerciseMutations() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["coding"] });
  return {
    create: useMutation({
      mutationFn: (body: ExerciseIn) => unwrap(api.POST("/api/v1/coding/exercises", { body })),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) =>
        unwrap(api.DELETE("/api/v1/coding/exercises/{exercise_id}", { params: { path: { exercise_id: id } } })),
      onSuccess: refresh,
    }),
  };
}

export function useSubmit(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["SubmissionIn"]) =>
      unwrap(
        api.POST("/api/v1/coding/exercises/{exercise_id}/submissions", {
          params: { path: { exercise_id: id } },
          body,
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["coding"] }),
  });
}

/** The hint ladder for a coding exercise. */
export function useExerciseHints(id: string) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: codingKeys.hints(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/coding/exercises/{exercise_id}/hints", { params: { path: { exercise_id: id } } })),
  });
  const next = useMutation({
    mutationFn: (body: Schemas["HintRequest"]) =>
      unwrap(
        api.POST("/api/v1/coding/exercises/{exercise_id}/hints", { params: { path: { exercise_id: id } }, body }),
      ),
    onSuccess: (data) => {
      qc.setQueryData(codingKeys.hints(id), data);
      void qc.invalidateQueries({ queryKey: ["ai"] });
    },
  });
  return { query, next };
}

/** The hint ladder for a question in a practice quiz. */
export function useQuestionHints(attemptId: string, questionId: string, enabled: boolean) {
  const qc = useQueryClient();
  const key = codingKeys.questionHints(attemptId, questionId);
  const path = { attempt_id: attemptId, question_id: questionId };
  const query = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET("/api/v1/attempts/{attempt_id}/responses/{question_id}/hints", { params: { path } })),
    enabled,
  });
  const next = useMutation({
    mutationFn: (body: Schemas["HintRequest"]) =>
      unwrap(api.POST("/api/v1/attempts/{attempt_id}/responses/{question_id}/hints", { params: { path }, body })),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      void qc.invalidateQueries({ queryKey: ["ai"] });
    },
  });
  return { query, next };
}

export const LANGUAGES = [
  { value: "python", label: "Python" },
  { value: "r", label: "R" },
] as const;
