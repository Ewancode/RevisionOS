import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, readCookie, toApiError, unwrap, type Schemas } from "@/lib/api/client";

export type Draft = Schemas["DraftOut"];
export type GenerateRequest = Schemas["GenerateRequest"];
export type Material = Schemas["MaterialOut"];
export type MaterialSummary = Schemas["MaterialSummary"];
export type Version = Schemas["VersionOut"];
export type Question = Schemas["QuestionOut"];
export type Flashcard = Schemas["FlashcardOut"];
export type Attempt = Schemas["AttemptOut"];
export type AttemptItem = Schemas["AttemptItem"];
export type QuizCreate = Schemas["QuizCreate"];
export type QuestionType = Question["type"];
export type Difficulty = Question["difficulty"];
export type MaterialKind = MaterialSummary["kind"];

/** One generated question or flashcard in a draft, with its check results. */
export interface DraftItem {
  type?: QuestionType;
  difficulty?: Difficulty;
  stem_md?: string;
  solution_md?: string;
  front_md?: string;
  back_md?: string;
  options?: string[] | null;
  correct_option?: number | null;
  true_or_false?: boolean | null;
  value?: number | null;
  unit?: string | null;
  expression?: string | null;
  accepted_answers?: string[] | null;
  rubric?: { point: string; marks: number }[] | null;
  model_answer?: string | null;
  sources?: number[];
  problems: string[];
  valid: boolean;
  repaired?: boolean;
}

export interface DraftPassage {
  n: number;
  document_id: string;
  filename: string;
  page_no: number;
  source_tier: "university" | "own";
}

export const QUESTION_TYPES: { value: QuestionType; label: string }[] = [
  { value: "multiple_choice", label: "Multiple choice" },
  { value: "true_false", label: "True or false" },
  { value: "numerical", label: "Numerical" },
  { value: "expression", label: "Algebraic answer" },
  { value: "short_answer", label: "Short answer" },
  { value: "explanation", label: "Explain" },
  { value: "derivation", label: "Derivation or proof" },
];
export const DIFFICULTIES: { value: Difficulty; label: string }[] = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
  { value: "exam", label: "Exam-level" },
];
export const MATERIAL_KINDS: { value: MaterialKind; label: string }[] = [
  { value: "guide", label: "Revision guide" },
  { value: "summary", label: "Summary" },
  { value: "formula_sheet", label: "Formula sheet" },
  { value: "worked_examples", label: "Worked examples" },
  { value: "definitions", label: "Definitions" },
  { value: "explanation", label: "Explanation" },
  { value: "concept_map", label: "Concept map" },
  { value: "notes", label: "Notes" },
];
export const label = <T extends string>(list: { value: T; label: string }[], value: T) =>
  list.find((x) => x.value === value)?.label ?? value;

export const studyKeys = {
  drafts: (moduleId: string) => ["drafts", moduleId] as const,
  draft: (id: string) => ["draft", id] as const,
  materials: (moduleId: string) => ["materials", moduleId] as const,
  material: (id: string) => ["material", id] as const,
  version: (materialId: string, versionId: string) => ["material", materialId, "version", versionId] as const,
  diff: (materialId: string, from: string, to: string) => ["material", materialId, "diff", from, to] as const,
  questions: (moduleId: string, filters: object) => ["questions", moduleId, filters] as const,
  flashcards: (moduleId: string) => ["flashcards", moduleId] as const,
  attempts: (moduleId: string) => ["attempts", moduleId] as const,
  attempt: (id: string) => ["attempt", id] as const,
};

// --- drafts -------------------------------------------------------------------------------

export function useDrafts(moduleId: string) {
  return useQuery({
    queryKey: studyKeys.drafts(moduleId),
    queryFn: () => unwrap(api.GET("/api/v1/drafts", { params: { query: { module_id: moduleId } } })),
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === "generating") ? 3000 : false),
  });
}

/** A draft, polled while Claude is still writing it. */
export function useDraft(id: string) {
  return useQuery({
    queryKey: studyKeys.draft(id),
    queryFn: () => unwrap(api.GET("/api/v1/drafts/{draft_id}", { params: { path: { draft_id: id } } })),
    refetchInterval: (query) => (query.state.data?.status === "generating" ? 2000 : false),
  });
}

export function useGenerate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GenerateRequest) => unwrap(api.POST("/api/v1/drafts", { body })),
    onSuccess: (draft) => qc.invalidateQueries({ queryKey: studyKeys.drafts(draft.module_id) }),
  });
}

export function useDraftActions(draft: Draft) {
  const qc = useQueryClient();
  const path = { params: { path: { draft_id: draft.id } } };
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: studyKeys.draft(draft.id) }),
      qc.invalidateQueries({ queryKey: ["drafts"] }),
      qc.invalidateQueries({ queryKey: ["materials"] }),
      qc.invalidateQueries({ queryKey: ["material"] }),
      qc.invalidateQueries({ queryKey: ["questions"] }),
      qc.invalidateQueries({ queryKey: ["flashcards"] }),
      qc.invalidateQueries({ queryKey: ["ai"] }),
    ]);
  return {
    save: useMutation({
      mutationFn: (body: Schemas["DraftSave"]) =>
        unwrap(api.POST("/api/v1/drafts/{draft_id}/save", { ...path, body })),
      onSuccess: refresh,
    }),
    regenerate: useMutation({
      mutationFn: (instructions: string | null) =>
        unwrap(api.POST("/api/v1/drafts/{draft_id}/regenerate", { ...path, body: { instructions } })),
      onSuccess: refresh,
    }),
    discard: useMutation({
      mutationFn: () => unwrap(api.POST("/api/v1/drafts/{draft_id}/discard", path)),
      onSuccess: refresh,
    }),
  };
}

// --- materials ----------------------------------------------------------------------------

export function useMaterials(moduleId: string) {
  return useQuery({
    queryKey: studyKeys.materials(moduleId),
    queryFn: () => unwrap(api.GET("/api/v1/materials", { params: { query: { module_id: moduleId } } })),
  });
}

export function useMaterial(id: string) {
  return useQuery({
    queryKey: studyKeys.material(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/materials/{material_id}", { params: { path: { material_id: id } } })),
  });
}

export function useVersion(materialId: string, versionId: string | null) {
  return useQuery({
    queryKey: studyKeys.version(materialId, versionId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/materials/{material_id}/versions/{version_id}", {
          params: { path: { material_id: materialId, version_id: versionId ?? "" } },
        }),
      ),
    enabled: versionId !== null,
  });
}

export function useDiff(materialId: string, from: string | null, to: string) {
  return useQuery({
    queryKey: studyKeys.diff(materialId, from ?? "", to),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/materials/{material_id}/diff", {
          params: { path: { material_id: materialId }, query: { from_version: from ?? "", to_version: to } },
        }),
      ),
    enabled: from !== null,
  });
}

export function useCreateMaterial() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["MaterialCreate"]) => unwrap(api.POST("/api/v1/materials", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["materials"] }),
  });
}

export function useMaterialActions(materialId: string) {
  const qc = useQueryClient();
  const path = { params: { path: { material_id: materialId } } };
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["material", materialId] }),
      qc.invalidateQueries({ queryKey: ["materials"] }),
      qc.invalidateQueries({ queryKey: ["trash"] }),
    ]);
  const versionPath = (versionId: string) => ({
    params: { path: { material_id: materialId, version_id: versionId } },
  });
  return {
    addVersion: useMutation({
      mutationFn: (body: Schemas["VersionCreate"]) =>
        unwrap(api.POST("/api/v1/materials/{material_id}/versions", { ...path, body })),
      onSuccess: refresh,
    }),
    restoreVersion: useMutation({
      mutationFn: (versionId: string) =>
        unwrap(api.POST("/api/v1/materials/{material_id}/versions/{version_id}/restore", versionPath(versionId))),
      onSuccess: refresh,
    }),
    deleteVersion: useMutation({
      mutationFn: (versionId: string) =>
        unwrap(api.DELETE("/api/v1/materials/{material_id}/versions/{version_id}", versionPath(versionId))),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: () => unwrap(api.DELETE("/api/v1/materials/{material_id}", path)),
      onSuccess: refresh,
    }),
  };
}

// --- question bank and flashcards -------------------------------------------------------------

export interface BankFilters {
  topic_id?: string;
  difficulty?: Difficulty;
  type?: QuestionType;
  result: "any" | "unattempted" | "wrong" | "right";
  status: "active" | "retired";
}

export function useQuestions(moduleId: string, filters: BankFilters) {
  return useQuery({
    queryKey: studyKeys.questions(moduleId, filters),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/questions", {
          params: {
            query: {
              module_id: moduleId,
              topic_id: filters.topic_id ? [filters.topic_id] : undefined,
              difficulty: filters.difficulty ? [filters.difficulty] : undefined,
              type: filters.type ? [filters.type] : undefined,
              result: filters.result,
              status: filters.status,
            },
          },
        }),
      ),
  });
}

export function useUpdateQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["QuestionUpdate"] }) =>
      unwrap(api.PATCH("/api/v1/questions/{question_id}", { params: { path: { question_id: id } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["questions"] }),
  });
}

export function useFlashcards(moduleId: string) {
  return useQuery({
    queryKey: studyKeys.flashcards(moduleId),
    queryFn: () => unwrap(api.GET("/api/v1/flashcards", { params: { query: { module_id: moduleId } } })),
  });
}

export function useFlashcardActions() {
  const qc = useQueryClient();
  const refresh = () =>
    Promise.all([qc.invalidateQueries({ queryKey: ["flashcards"] }), qc.invalidateQueries({ queryKey: ["trash"] })]);
  return {
    create: useMutation({
      mutationFn: (body: Schemas["FlashcardCreate"]) => unwrap(api.POST("/api/v1/flashcards", { body })),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) =>
        unwrap(api.DELETE("/api/v1/flashcards/{card_id}", { params: { path: { card_id: id } } })),
      onSuccess: refresh,
    }),
  };
}

// --- quizzes and attempts ------------------------------------------------------------------------

export function useAttempts(moduleId: string) {
  return useQuery({
    queryKey: studyKeys.attempts(moduleId),
    queryFn: () => unwrap(api.GET("/api/v1/attempts", { params: { query: { module_id: moduleId } } })),
  });
}

export function useStartQuiz() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: QuizCreate) => unwrap(api.POST("/api/v1/quizzes", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["attempts"] }),
  });
}

/** An attempt; polled while Claude is marking it. */
export function useAttempt(id: string) {
  return useQuery({
    queryKey: studyKeys.attempt(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/attempts/{attempt_id}", { params: { path: { attempt_id: id } } })),
    refetchInterval: (query) => (query.state.data?.status === "marking" ? 2500 : false),
  });
}

export function useAttemptActions(attemptId: string) {
  const qc = useQueryClient();
  const set = (attempt: Attempt) => {
    qc.setQueryData(studyKeys.attempt(attemptId), attempt);
    void qc.invalidateQueries({ queryKey: ["attempts"] });
    void qc.invalidateQueries({ queryKey: ["questions"] });
    void qc.invalidateQueries({ queryKey: ["ai"] });
  };
  return {
    save: useMutation({
      mutationFn: ({ questionId, body }: { questionId: string; body: Schemas["ResponseSave"] }) =>
        unwrap(
          api.PUT("/api/v1/attempts/{attempt_id}/responses/{question_id}", {
            params: { path: { attempt_id: attemptId, question_id: questionId } },
            body,
          }),
        ),
    }),
    submit: useMutation({
      mutationFn: () =>
        unwrap(api.POST("/api/v1/attempts/{attempt_id}/submit", { params: { path: { attempt_id: attemptId } } })),
      onSuccess: set,
    }),
    dispute: useMutation({
      mutationFn: (answerId: string) =>
        unwrap(api.POST("/api/v1/answers/{answer_id}/dispute", { params: { path: { answer_id: answerId } } })),
      onSuccess: set,
    }),
    override: useMutation({
      mutationFn: ({ answerId, score }: { answerId: string; score: number }) =>
        unwrap(
          api.POST("/api/v1/answers/{answer_id}/override", {
            params: { path: { answer_id: answerId } },
            body: { score },
          }),
        ),
      onSuccess: set,
    }),
  };
}

/** Upload a photo of working as the raw body; returns the transcription. */
export async function uploadPhoto(
  attemptId: string,
  questionId: string,
  file: File,
): Promise<Schemas["PhotoTranscription"]> {
  const headers: Record<string, string> = { "Content-Type": "application/octet-stream" };
  const csrf = readCookie("__Host-rev_csrf");
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const origin = globalThis.location?.origin ?? "";
  const query = new URLSearchParams({ filename: file.name });
  let response: Response;
  try {
    response = await fetch(
      `${origin}/api/v1/attempts/${attemptId}/responses/${questionId}/photo?${query.toString()}`,
      { method: "POST", headers, body: file, credentials: "same-origin" },
    );
  } catch {
    throw new ApiError(0, "network_error", "The upload failed. Check your connection.");
  }
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) throw toApiError(response.status, body);
  return body as Schemas["PhotoTranscription"];
}
