import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";

export type Year = Schemas["YearOut"];
export type Module = Schemas["ModuleOut"];
export type TopicNode = Schemas["TopicNode"];

export const keys = {
  years: ["years"] as const,
  modules: (yearId: string | undefined, status: "active" | "archived" | "all") =>
    ["modules", yearId ?? "all", status] as const,
  module: (id: string) => ["module", id] as const,
  topics: (moduleId: string) => ["topics", moduleId] as const,
  trash: ["trash"] as const,
};

// --- years -------------------------------------------------------------------

export function useYears() {
  return useQuery({ queryKey: keys.years, queryFn: () => unwrap(api.GET("/api/v1/years")) });
}

export function useCreateYear() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["YearCreate"]) => unwrap(api.POST("/api/v1/years", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.years }),
  });
}

export function useMakeYearCurrent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (yearId: string) =>
      unwrap(
        api.POST("/api/v1/years/{year_id}/make-current", { params: { path: { year_id: yearId } } }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.years }),
  });
}

// --- modules -----------------------------------------------------------------

export function useModules(yearId: string | undefined, status: "active" | "archived" | "all" = "active") {
  return useQuery({
    queryKey: keys.modules(yearId, status),
    queryFn: () =>
      unwrap(api.GET("/api/v1/modules", { params: { query: { year_id: yearId, status } } })),
    enabled: yearId !== undefined,
  });
}

export function useModule(moduleId: string, enabled = true) {
  return useQuery({
    queryKey: keys.module(moduleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/modules/{module_id}", { params: { path: { module_id: moduleId } } })),
    enabled: enabled && moduleId !== "",
  });
}

function useInvalidateStructure() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["modules"] }),
      qc.invalidateQueries({ queryKey: ["module"] }),
      qc.invalidateQueries({ queryKey: ["topics"] }),
      qc.invalidateQueries({ queryKey: keys.trash }),
    ]);
}

export function useCreateModule() {
  const invalidate = useInvalidateStructure();
  return useMutation({
    mutationFn: (body: Schemas["ModuleCreate"]) => unwrap(api.POST("/api/v1/modules", { body })),
    onSuccess: invalidate,
  });
}

export function useUpdateModule(moduleId: string) {
  const invalidate = useInvalidateStructure();
  return useMutation({
    mutationFn: (body: Schemas["ModuleUpdate"]) =>
      unwrap(
        api.PATCH("/api/v1/modules/{module_id}", { params: { path: { module_id: moduleId } }, body }),
      ),
    onSuccess: invalidate,
  });
}

export function useDeleteModule() {
  const invalidate = useInvalidateStructure();
  return useMutation({
    mutationFn: (moduleId: string) =>
      unwrap(api.DELETE("/api/v1/modules/{module_id}", { params: { path: { module_id: moduleId } } })),
    onSuccess: invalidate,
  });
}

// --- topics ------------------------------------------------------------------

export function useTopicTree(moduleId: string) {
  return useQuery({
    queryKey: keys.topics(moduleId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/modules/{module_id}/topics", { params: { path: { module_id: moduleId } } }),
      ),
  });
}

export function useTopicMutations(moduleId: string) {
  const qc = useQueryClient();
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: keys.topics(moduleId) }),
      qc.invalidateQueries({ queryKey: keys.trash }),
    ]);
  const create = useMutation({
    mutationFn: (body: Schemas["TopicCreate"]) =>
      unwrap(
        api.POST("/api/v1/modules/{module_id}/topics", {
          params: { path: { module_id: moduleId } },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["TopicUpdate"] }) =>
      unwrap(api.PATCH("/api/v1/topics/{topic_id}", { params: { path: { topic_id: id } }, body })),
    onSuccess: refresh,
  });
  const move = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["TopicMove"] }) =>
      unwrap(
        api.POST("/api/v1/topics/{topic_id}/move", { params: { path: { topic_id: id } }, body }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/v1/topics/{topic_id}", { params: { path: { topic_id: id } } })),
    onSuccess: refresh,
  });
  return { create, update, move, remove };
}

// --- trash -------------------------------------------------------------------

export function useTrash() {
  return useQuery({ queryKey: keys.trash, queryFn: () => unwrap(api.GET("/api/v1/trash")) });
}

export function useRestore() {
  const invalidate = useInvalidateStructure();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      kind,
      id,
    }: {
      kind: "module" | "topic" | "document" | "material" | "flashcard" | "exercise";
      id: string;
    }): Promise<void> => {
      if (kind === "module") {
        await unwrap(
          api.POST("/api/v1/modules/{module_id}/restore", { params: { path: { module_id: id } } }),
        );
      } else if (kind === "document") {
        await unwrap(
          api.POST("/api/v1/documents/{document_id}/restore", {
            params: { path: { document_id: id } },
          }),
        );
      } else if (kind === "material") {
        await unwrap(
          api.POST("/api/v1/materials/{material_id}/restore", { params: { path: { material_id: id } } }),
        );
      } else if (kind === "exercise") {
        await unwrap(
          api.POST("/api/v1/coding/exercises/{exercise_id}/restore", { params: { path: { exercise_id: id } } }),
        );
      } else if (kind === "flashcard") {
        await unwrap(
          api.POST("/api/v1/flashcards/{card_id}/restore", { params: { path: { card_id: id } } }),
        );
      } else {
        await unwrap(
          api.POST("/api/v1/topics/{topic_id}/restore", { params: { path: { topic_id: id } } }),
        );
      }
    },
    onSuccess: () =>
      Promise.all([
        invalidate(),
        qc.invalidateQueries({ queryKey: ["documents"] }),
        qc.invalidateQueries({ queryKey: ["materials"] }),
        qc.invalidateQueries({ queryKey: ["flashcards"] }),
        qc.invalidateQueries({ queryKey: ["coding"] }),
      ]),
  });
}
