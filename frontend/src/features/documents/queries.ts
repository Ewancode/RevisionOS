import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { api, ApiError, readCookie, toApiError, unwrap, type Schemas } from "@/lib/api/client";

export type Doc = Schemas["DocumentOut"];
export type Page = Schemas["PageOut"];
export type SourceTier = Doc["source_tier"];
export type MaterialKind = Doc["material_kind"];
/** One server-sent progress event (GET /documents/{id}/events). */
type Progress = Pick<Doc, "status" | "stage" | "progress" | "error_code">;

export const MATERIAL_KINDS: { value: MaterialKind; label: string }[] = [
  { value: "lecture", label: "Lecture" },
  { value: "problem_sheet", label: "Problem sheet" },
  { value: "solutions", label: "Solutions" },
  { value: "past_paper", label: "Past paper" },
  { value: "notes", label: "Notes" },
  { value: "other", label: "Other" },
];

export const ACCEPT =
  ".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp,.heic,.heif";

const TERMINAL = new Set(["ready", "failed"]);

export const docKeys = {
  list: (moduleId: string) => ["documents", moduleId] as const,
  one: (id: string) => ["document", id] as const,
  pages: (id: string) => ["document", id, "pages"] as const,
  budget: ["ai", "budget"] as const,
};

export function useDocuments(moduleId: string) {
  return useQuery({
    queryKey: docKeys.list(moduleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/documents", { params: { query: { module_id: moduleId } } })),
  });
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: docKeys.one(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/documents/{document_id}", { params: { path: { document_id: id } } })),
  });
}

export function usePages(id: string, enabled = true) {
  return useQuery({
    queryKey: docKeys.pages(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/documents/{document_id}/pages", { params: { path: { document_id: id } } }),
      ),
    enabled,
  });
}

export function useBudget() {
  return useQuery({
    queryKey: docKeys.budget,
    queryFn: () => unwrap(api.GET("/api/v1/ai/budget")),
  });
}

/**
 * Follow a document's processing over server-sent events, writing progress
 * into the query cache. When it finishes, refresh everything that depends on
 * it (pages, the module's list, the AI budget).
 */
export function useDocumentProgress(doc: Doc | undefined) {
  const qc = useQueryClient();
  const id = doc?.id;
  const active = doc !== undefined && !TERMINAL.has(doc.status);
  useEffect(() => {
    if (!id || !active || typeof EventSource === "undefined") return;
    const source = new EventSource(`/api/v1/documents/${id}/events`);
    source.onmessage = (event: MessageEvent<string>) => {
      const progress = JSON.parse(event.data) as Progress;
      qc.setQueryData<Doc>(docKeys.one(id), (old) => (old ? { ...old, ...progress } : old));
      qc.setQueriesData<Doc[]>({ queryKey: ["documents"] }, (list) =>
        list?.map((d) => (d.id === id ? { ...d, ...progress } : d)),
      );
      if (TERMINAL.has(progress.status)) {
        source.close();
        void qc.invalidateQueries({ queryKey: ["document", id] });
        void qc.invalidateQueries({ queryKey: ["documents"] });
        void qc.invalidateQueries({ queryKey: docKeys.budget });
      }
    };
    // The browser reconnects on its own; the server closes the stream when done.
    return () => source.close();
  }, [id, active, qc]);
}

export interface UploadParams {
  moduleId: string;
  sourceTier: SourceTier;
  materialKind: MaterialKind;
  topicId?: string;
  week?: number;
}

/**
 * Upload the file as the raw request body. XHR rather than fetch because only
 * XHR reports upload progress, which matters for a 100 MB PDF.
 */
export function uploadDocument(
  file: File,
  params: UploadParams,
  onProgress: (fraction: number) => void,
): Promise<Doc> {
  const query = new URLSearchParams({
    filename: file.name,
    module_id: params.moduleId,
    source_tier: params.sourceTier,
    material_kind: params.materialKind,
  });
  if (params.topicId) query.set("topic_id", params.topicId);
  if (params.week !== undefined) query.set("week", String(params.week));

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/documents?${query.toString()}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    const csrf = readCookie("__Host-rev_csrf");
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }
      if (xhr.status === 202) resolve(body as Doc);
      else reject(toApiError(xhr.status, body));
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", "The upload failed. Check your connection."));
    xhr.send(file);
  });
}

export function useDocumentMutations(id: string) {
  const qc = useQueryClient();
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["document", id] }),
      qc.invalidateQueries({ queryKey: ["documents"] }),
      qc.invalidateQueries({ queryKey: ["trash"] }),
    ]);
  const path = { params: { path: { document_id: id } } };
  return {
    update: useMutation({
      mutationFn: (body: Schemas["DocumentUpdate"]) =>
        unwrap(api.PATCH("/api/v1/documents/{document_id}", { ...path, body })),
      onSuccess: refresh,
    }),
    reprocess: useMutation({
      mutationFn: () => unwrap(api.POST("/api/v1/documents/{document_id}/reprocess", path)),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: () => unwrap(api.DELETE("/api/v1/documents/{document_id}", path)),
      onSuccess: refresh,
    }),
    correct: useMutation({
      mutationFn: ({ pageNo, markdown }: { pageNo: number; markdown: string }) =>
        unwrap(
          api.PUT("/api/v1/documents/{document_id}/pages/{page_no}", {
            params: { path: { document_id: id, page_no: pageNo } },
            body: { markdown },
          }),
        ),
      onSuccess: refresh,
    }),
    retranscribe: useMutation({
      mutationFn: (pageNo: number) =>
        unwrap(
          api.POST("/api/v1/documents/{document_id}/pages/{page_no}/retranscribe", {
            params: { path: { document_id: id, page_no: pageNo } },
          }),
        ),
      onSuccess: refresh,
    }),
  };
}
